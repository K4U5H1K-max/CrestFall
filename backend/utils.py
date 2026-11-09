from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentAction:
    agent_id: str
    action_type: str
    parameters: dict = field(default_factory=dict)
    timestep: int = 0


@dataclass
class AgentTransition:
    timestep: int
    agent_id: str
    observation: dict
    action: AgentAction
    reward: float
    next_observation: dict
    done: bool
    result: dict


class AgentProtocol:
    """Common observation, decision, and execution boundary for operational agents."""

    def observe(self, state=None):
        observation = {
            "agent_id": self._agent_id(),
            "agent_type": type(self).__name__,
            "state": getattr(self, "state", "available"),
            "queue_size": len(getattr(self, "order_queue", [])),
        }
        if state is not None:
            observation["timestep"] = getattr(state, "time", 0)
        return observation

    def select_action(self, observation, timestep=0):
        action = self._model().predict(
            observation,
            self.available_actions() if hasattr(self, "available_actions") else [
                {"action_type": "wait", "parameters": {}}
            ],
        )
        return AgentAction(
            self._agent_id(),
            action["action_type"],
            action.get("parameters", {}),
            timestep,
        )

    def available_actions(self):
        return [{"action_type": "wait", "parameters": {}}]

    def _model(self):
        if getattr(self, "model", None) is None:
            from backend.model.placeholder import PlaceholderModel

            self.model = PlaceholderModel()
        return self.model

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"],
                action["action_type"],
                action.get("parameters", {}),
                action.get("timestep", 0),
            )
        if action.agent_id != self._agent_id():
            raise ValueError(
                f"Action belongs to {action.agent_id}, not {self._agent_id()}"
            )

        if action.action_type == "wait":
            result = self.wait()
            return {"success": bool(result), "action": "wait"}
        raise ValueError(
            f"{type(self).__name__} does not implement action "
            f"{action.action_type!r}"
        )

    def _validate_action_owner(self, action):
        if action.agent_id != self._agent_id():
            raise ValueError(
                f"Action belongs to {action.agent_id}, not {self._agent_id()}"
            )

    def _agent_id(self):
        for attribute in (
            "agent_id", "picker_id", "inventory_id", "packer_id",
            "dispatch_id", "delivery_id", "return_evaluation_id", "customer_id",
        ):
            if hasattr(self, attribute):
                return getattr(self, attribute)
        raise AttributeError("Agent has no identifier")

    def _neighbor_list(self):
        neighbors = getattr(self, "neighboring_agents", [])
        return list(neighbors.keys()) if isinstance(neighbors, dict) else list(neighbors)

    @staticmethod
    def _is_return_route(payload):
        return payload.get("route_type") == "return" or bool(
            payload.get("return_request")
        )


class SimulationState:
    def __init__(
        self,
        orders=None,
        agents=None,
        time=0,
        weather="Normal",
        malicious_factors=None,
        action_queue=None,
    ):
        self.orders = [] if orders is None else orders
        self.agents = [] if agents is None else agents
        self.time = time
        self.weather = weather
        self.malicious_factors = [None] if malicious_factors is None else malicious_factors
        self.action_queue = [] if action_queue is None else action_queue


class SimulationSate(SimulationState):
    """Backward-compatible spelling retained for existing callers."""


class SimulationEngine:
    def __init__(self, state, models=None):
        self.state = state
        self.transitions = []
        if models is None:
            from backend.model.loader import load_models

            models = load_models()
        self.models = models
        for agent in self.state.agents:
            if getattr(agent, "model", None) is None:
                role = self._role_for(agent)
                agent.model = self.models.get(role)
            if isinstance(agent, InventoryAgent):
                if "predictive_refill" in self.models:
                    agent.predictive_refill_model = self.models.get(
                        "predictive_refill"
                    )
                agent.initialize_predictive_refill()
        self._synchronize_inventory_time()

    def _synchronize_inventory_time(self):
        for agent in self.state.agents:
            if isinstance(agent, InventoryAgent):
                elapsed = self.state.time - agent.simulation_time
                if elapsed > 0:
                    agent.wait(elapsed)

    @staticmethod
    def _role_for(agent):
        role = type(agent).__name__.replace("Agent", "")
        return {
            "OrderManagement": "order_management",
            "Picker": "picker",
            "Inventory": "inventory",
            "Packer": "packer",
            "Dispatch": "dispatch",
            "Delivery": "delivery",
            "ReturnEvaluation": "return_evaluation",
            "Customer": "customer",
        }.get(role, role.lower())

    def step(self, actions=None):
        self._synchronize_inventory_time()
        timestep = self.state.time
        actions = self._actions_for_timestep(actions, timestep)
        transitions = []
        for agent, action in actions:
            observation = agent.observe(self.state)
            result = agent.execute_action(action, self.state)
            next_observation = agent.observe(self.state)
            transitions.append(
                AgentTransition(
                    timestep=timestep,
                    agent_id=agent._agent_id(),
                    observation=observation,
                    action=action,
                    reward=float(result.get("reward", 0.0)),
                    next_observation=next_observation,
                    done=bool(result.get("done", False)),
                    result=result,
                )
            )
        self.transitions.extend(transitions)
        self.state.time += 1
        self._synchronize_inventory_time()
        return transitions

    def _actions_for_timestep(self, actions, timestep):
        if actions is None:
            return [
                (agent, agent.select_action(agent.observe(self.state), timestep))
                for agent in self.state.agents
            ]
        if len(actions) != len({action.agent_id for action in actions}):
            raise ValueError("Each agent may submit at most one action per timestep")
        agents_by_id = {agent._agent_id(): agent for agent in self.state.agents}
        selected = []
        for action in actions:
            if action.timestep != timestep:
                raise ValueError(
                    f"Action timestep {action.timestep} does not match {timestep}"
                )
            if action.agent_id not in agents_by_id:
                raise ValueError(f"Unknown agent: {action.agent_id}")
            selected.append((agents_by_id[action.agent_id], action))
        return selected


class orderRequest:
    def __init__(self, order_id, customer_name, items, location, priority=0):
        #self.order_id = order_id #will be generated by the Order management agent
        self.customer_name = customer_name
        self.location = location
        #below varibles are assigined  by Order management agent
        self.items = items  # List of items in the order
        self.priority = priority #initially set to 0, can be updated by Order management agent 





class order:#order request becomes order if the order magement agent releases it to the sysetm ie when a picker agent is available
    def __init__(self, order_id, customer_name, items, location, health, status, priority=0):
        self.order_id = order_id#will be generated by the Order management agent
        self.customer_name = customer_name # not important at all. but would be good to have for explainabilty layer and add aesthetics to the system.
        self.location = location #my idea is to have a zone based hueristics for the delivery agent to pick up the order and deliver it to the customer, so location is important for the delivery agent to know where to go and how to get there and how long will it take, determines priority and affects the helath of the order(each individual item has health )
        self.items = items  # Dictionary of items in the order with their quantities and healths
        self.priority = priority #initially set to 0, can be updated by Order management agent
        #self.health = health #health of the order, can be updated by factors such as time,weather, etc. for each individual item in the order, can be updated by any of the factors that would affect the health of the order, such as time, weather, etc. for each individual item in the order(most likely will be a dictionary with item name as key and health as value)
        self.status= status #stuatus of the order i.e. pending, in progress, completed, failed, return, etc. can be updated by any of the agents with its appropriate action




class LegacySimulationSate:
    def __init__(self, orders, agents, time, weather="Normal",
                 malicious_factors=None, action_queue=None):
        self.orders = orders  # List of order objects
        self.agents = agents  # List of agent objects(will most likely be a graph with nodes as agents and edges as the communication between them only for backend purposes, not for the frontend)
        self.time = time  # Current simulation time(currently thinking about having single epoch of action(set of sigular/multiple actions) at a single time that means at a single simulated timestep multiple actions can be peformed by multiple agents sequentially so that flow is not interrupred(hence no parallel execution of actions by a single agent at a single timestep))
        self.weather = weather  # Current weather condition
        self.malicious_factors = (
            [None] if malicious_factors is None else malicious_factors
        )
        self.action_queue = [] if action_queue is None else action_queue




class OrderManagementAgent(AgentProtocol):
    def __init__(self, agent_id, order_queue=None, neighboring_agents=None, model=None):
        self.agent_id = agent_id
        self.order_queue = [] if order_queue is None else order_queue
        self.neighboring_agents = {} if neighboring_agents is None else neighboring_agents
        self.model = model

    def _neighbors(self):
        return self._neighbor_list()

    def _pickers(self):
        return [
            agent for agent in self._neighbors()
            if isinstance(agent, PickerAgent)
        ]

    def _dispatchers(self):
        return [
            agent for agent in self._neighbors()
            if isinstance(agent, DispatchAgent)
        ]

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update(
            {
                "orders": [
                    {
                        "order_id": order_obj.order_id,
                        "status": order_obj.status,
                        "priority": order_obj.priority,
                        "items": dict(order_obj.items),
                    }
                    for order_obj in self.order_queue
                ],
                "available_pickers": [
                    picker.picker_id
                    for picker in self._pickers()
                    if picker.state == "wait"
                ],
                "action_mask": self.available_actions(),
            }
        )
        return observation

    def available_actions(self):
        actions = [
            {
                "action_type": "release_order",
                "parameters": {"order_id": order_obj.order_id},
            }
            for order_obj in self.order_queue
            if order_obj.status == "pending"
        ]
        actions.extend(
            {
                "action_type": "accept_return_request",
                "parameters": {"order_id": order_obj.order_id},
            }
            for order_obj in self.order_queue
            if order_obj.status == "return_requested"
        )
        actions.append({"action_type": "wait", "parameters": {}})
        return actions


    def process_order_request(self, order_request):
        # Process the order request and create an order object
        order_id = self.generate_order_id()  # Generate a unique order ID
        health = {item: 1.0 for item in order_request.items}
        status = "pending"  # Initial status of the order
        order_obj = order(order_id, order_request.customer_name, order_request.items, order_request.location, health, status, 0)
        order_obj.priority = self.calculate_priority(order_obj)
        self.order_queue.append(order_obj)
        return order_obj

    
    def generate_order_id(self):
        import uuid
        # after generating the order id, update the order database with the new order id and the order details, so that the order can be tracked and managed throughout the system.
        return str(uuid.uuid4())  # Generate a unique order ID using UUID
    
    
    def calculate_priority(self, order_obj):
        #need to find a way to calculate a quntififable way to categorise an order into 3 priority levels: high, medium, low based on the location of the order and the items in the order and the health of the order and the weather conditions and the time of the day and the malicious factors affecting the simulation
        del order_obj
        return 0

    # def calculate_initial_helath(self, order_obj):
    #     #initial health is full(100) for all items
    #     for item in order_obj.items:
    #         order_obj.health[item] = 100
    #     #this is initial health


    def release_order(self, order_obj):
        # Release the order to the system (e.g., assign it to a picker agent)
        #assigned only when a picker agent is available
        picker = next(
            (
                agent
                for agent in self._neighbors()
                if isinstance(agent, PickerAgent) and agent.state == "wait"
            ),
            None,
        )
        if picker is None:
            return False

        picker.order_queue.append(order_obj)
        if isinstance(self.neighboring_agents, dict):
            self.neighboring_agents.setdefault(picker, []).append(order_obj)
        order_obj.status = "picking"
        picker.state = "picking"
        return True


    def accept_return_request(self, order_obj, returned_items=None):
        # Accept a return request for the order
        dispatch = next(
            (
                agent
                for agent in self._dispatchers()
                if len(agent.order_queue) < agent.dispatch_capacity
            ),
            None,
        )
        if dispatch is None:
            return False

        if returned_items is None:
            health = getattr(order_obj, "health", {})
            returned_items = {
                item: (quantity, health.get(item, 1.0))
                for item, quantity in order_obj.items.items()
            }
        order_obj.status = "return_requested"
        dispatch.order_queue.append({
            "order_id": order_obj.order_id,
            "order": order_obj,
            "return_request": True,
            "route_type": "return",
            "items": returned_items,
            "status": "return_requested",
        })
        return True


    def wait(self):
        #wait until the picker is ready or no action is needed ie there is no new orders.
        while self.order_queue:
            if not self.release_order(self.order_queue[0]):
                return False
            self.order_queue.pop(0)
        return True

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}),                 action.get("timestep", 0)
            )
        self._validate_action_owner(action)
        if action.action_type == "release_order":
            order_id = action.parameters["order_id"]
            order_obj = next(
                (candidate for candidate in self.order_queue
                 if candidate.order_id == order_id),
                None,
            )
            if order_obj is None:
                raise ValueError(f"Unknown queued order: {order_id}")
            released = self.release_order(order_obj)
            if released:
                self.order_queue.remove(order_obj)
            return {"success": released, "action": "release_order"}
        if action.action_type == "accept_return_request":
            order_id = action.parameters["order_id"]
            order_obj = next(
                (
                    candidate for candidate in self.order_queue
                    if candidate.order_id == order_id
                ),
                None,
            )
            if order_obj is None:
                raise ValueError(f"Unknown queued order: {order_id}")
            accepted = self.accept_return_request(order_obj)
            if accepted:
                self.order_queue.remove(order_obj)
            return {
                "success": accepted,
                "action": "accept_return_request",
            }
        return super().execute_action(action, state)


class PickerAgent(AgentProtocol):
    def __init__(self, picker_id, item_capacity, order_queue=None, items=None, neighboring_agents=None, state="wait", model=None):
        self.picker_id = picker_id
        self.item_capacity = item_capacity  # Maximum number of items the picker can carry
        self.order_queue = [] if order_queue is None else order_queue
        self.items = {} if items is None else items
        self.neighboring_agents = {} if neighboring_agents is None else neighboring_agents
        self.state = state
        self.available_items = []
        self.action_queue = {}
        self.last_picked_order_id = None
        self.blocked_orders = {}
        self.order_registry = {}
        self.carried_items = {}
        self.model = model

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update(
            {
                "orders": [
                    {
                        "order_id": order.order_id,
                        "status": order.status,
                        "remaining_items": self._remaining_items(order),
                    }
                    for order in self.order_queue
                ],
                "blocked_orders": list(self.blocked_orders),
                "picked_items": {
                    order_id: {
                        item: list(healths)
                        for item, healths in picked.items()
                    }
                    for order_id, picked in self.items.items()
                },
                "carried_items": {
                    order_id: {
                        item: list(healths)
                        for item, healths in carried.items()
                    }
                    for order_id, carried in self.carried_items.items()
                },
                "available_items": list(self.available_items),
                "capacity_remaining": self._capacity_remaining(),
                "action_mask": self.available_actions(),
            }
        )
        return observation

    def _remaining_items(self, order_obj):
        picked = self.items.get(order_obj.order_id, {})
        return {
            item: max(quantity - len(picked.get(item, [])), 0)
            for item, quantity in order_obj.items.items()
            if quantity > len(picked.get(item, []))
        }

    def _capacity_remaining(self):
        queued = sum(len(actions) for actions in self.action_queue.values())
        return max(self.item_capacity - queued - self._carried_quantity(), 0)

    def _carried_quantity(self):
        return sum(
            len(healths)
            for carried in self.carried_items.values()
            for healths in carried.values()
        )

    def _order_is_carried(self, order_id):
        order_obj = self.order_registry.get(order_id)
        return order_obj is not None and order_obj.status not in {
            "packing", "packed", "completed"
        }

    def _connected_packers(self):
        neighbors = (
            self.neighboring_agents.keys()
            if isinstance(self.neighboring_agents, dict)
            else self.neighboring_agents
        )
        return [
            agent for agent in neighbors if isinstance(agent, PackerAgent)
        ]

    def _has_packer_capacity(self, order_id=None):
        return any(
            order_id in {
                package["order_id"] for package in packer.packages
            }.union(
                queued["order_id"] for queued in packer.order_queue
            )
            or len({
                package["order_id"] for package in packer.packages
            }.union(
                queued["order_id"] for queued in packer.order_queue
            )) < packer.package_capacity
            for packer in self._connected_packers()
        )

    def _is_legal_picker_action(self, action_type, parameters):
        if action_type == "wait":
            return True, ""

        order_id = parameters.get("order_id")
        order_obj = self.order_registry.get(order_id)
        if order_obj is None:
            order_obj = next(
                (
                    candidate for candidate in self.order_queue
                    if candidate.order_id == order_id
                ),
                None,
            )
        if order_obj is None:
            return False, f"Unknown order: {order_id}"

        remaining = self._remaining_items(order_obj)
        if order_obj.status in {"packing", "packed", "completed"}:
            return False, f"Order is not active: {order_id}"
        if (
            order_obj.status == "on-hold"
            and action_type not in {"pick", "unload_to_packer", "move_to_packer"}
        ):
            return False, f"Order is waiting for inventory: {order_id}"

        if action_type == "find_items":
            if not remaining:
                return False, "Order has no remaining items"
            if order_id in self.action_queue:
                return False, "Order already has queued actions"
            if self._capacity_remaining() < 1:
                return False, "Picker capacity is full"
            return True, ""

        if action_type == "pick":
            item = parameters.get("item")
            if item not in remaining:
                return False, f"Item is not required: {item}"
            if not any(
                action["item"] == item
                for action in self.action_queue.get(order_id, [])
            ):
                return False, f"No queued pick action for item: {item}"
            inventory = self._inventory_agent()
            if inventory is None or inventory.items.get(item, 0) < 1:
                return False, f"Item is unavailable in inventory: {item}"
            if self.item_capacity - self._carried_quantity() < 1:
                return False, "Picker capacity is full"
            return True, ""

        if action_type == "move_to_packer":
            if remaining:
                return False, f"Order is incomplete: {order_id}"
            if not self.carried_items.get(order_id):
                return False, f"No carried items for order: {order_id}"
            if not self._has_packer_capacity(order_id):
                return False, "No connected packer has capacity"
            return True, ""

        if action_type == "unload_to_packer":
            if not self.carried_items.get(order_id):
                return False, f"No carried items for order: {order_id}"
            if not self._has_packer_capacity(order_id):
                return False, "No connected packer has capacity"
            return True, ""

        return False, f"Unsupported picker action: {action_type}"

    def _require_legal_picker_action(self, action_type, parameters):
        legal, reason = self._is_legal_picker_action(action_type, parameters)
        if not legal:
            raise ValueError(reason)

    def _candidate_orders(self):
        queued = {order_obj.order_id for order_obj in self.order_queue}
        orders = list(self.order_queue)
        orders.extend(
            order_obj
            for order_id, order_obj in self.order_registry.items()
            if order_id not in queued
            and (
                order_obj.status == "picked"
                or (
                    order_obj.status == "on-hold"
                    and order_id in self.action_queue
                )
            )
        )
        return orders

    def available_actions(self):
        actions = []
        for order_obj in self._candidate_orders():
            order_id = order_obj.order_id
            remaining = self._remaining_items(order_obj)
            find_action = {
                "action_type": "find_items",
                "parameters": {"order_id": order_id},
            }
            if self._is_legal_picker_action(
                find_action["action_type"], find_action["parameters"]
            )[0]:
                actions.append(find_action)

            for queued_action in self.action_queue.get(order_id, []):
                pick_action = {
                    "action_type": "pick",
                    "parameters": {
                        "order_id": order_id,
                        "item": queued_action["item"],
                    },
                }
                if self._is_legal_picker_action(
                    pick_action["action_type"], pick_action["parameters"]
                )[0]:
                    actions.append(pick_action)

            move_action = {
                "action_type": "move_to_packer",
                "parameters": {"order_id": order_id},
            }
            if not remaining and self._is_legal_picker_action(
                move_action["action_type"], move_action["parameters"]
            )[0]:
                actions.append(move_action)
            unload_action = {
                "action_type": "unload_to_packer",
                "parameters": {"order_id": order_id},
            }
            if self._is_legal_picker_action(
                unload_action["action_type"], unload_action["parameters"]
            )[0]:
                actions.append(unload_action)
        actions.append({"action_type": "wait", "parameters": {}})
        return actions

    def _inventory_agent(self):
        return next(
            (
                agent
                for agent in self._neighbor_list()
                if isinstance(agent, InventoryAgent)
            ),
            None,
        )

    @staticmethod
    def _order_and_items(order_queue):
        order_obj = order_queue if hasattr(order_queue, "order_id") else None
        if order_obj is None and isinstance(order_queue, (list, tuple)):
            if len(order_queue) == 1 and hasattr(order_queue[0], "order_id"):
                order_obj = order_queue[0]
        items = order_obj.items if order_obj is not None else order_queue
        return order_obj, items

    def find_items(self, order_queue):
        inventory = self._inventory_agent()
        if inventory is None:
            raise RuntimeError("Picker is not connected to an inventory agent")

        order_obj, items = self._order_and_items(order_queue)
        if order_obj is None:
            self.available_items = inventory.check_availability(items)
            return self.available_items

        order_id = order_obj.order_id if order_obj is not None else None
        self.order_registry[order_id] = order_obj
        self._require_legal_picker_action(
            "find_items", {"order_id": order_id}
        )
        picked = self.items.setdefault(order_id, {})
        remaining = {
            item: max(quantity - len(picked.get(item, [])), 0)
            for item, quantity in items.items()
        }
        remaining = {item: quantity for item, quantity in remaining.items() if quantity}
        if not remaining:
            order_obj.status = "picked"
            return []

        available = inventory.check_availability(
            remaining, picker=self, order_id=order_id
        )
        queued = sum(
            1
            for actions in self.action_queue.values()
            for action in actions
            if action["order_id"] == order_id
        )
        capacity_remaining = self._capacity_remaining()
        for item in available[:capacity_remaining]:
            self.action_queue.setdefault(order_id, []).append(
                {"item": item, "order_id": order_id}
            )

        expected = sum(remaining.values())
        if len(available) < expected:
            order_obj.status = "on-hold"
            self.blocked_orders[order_id] = order_obj
            self.order_queue = [
                queued_order
                for queued_order in self.order_queue
                if queued_order.order_id != order_id
            ]
        else:
            order_obj.status = "picking"
        self.available_items = available
        return available

    def pick_items(self, item, order_id=None):
        inventory = self._inventory_agent()
        if inventory is None:
            raise RuntimeError("Picker is not connected to an inventory agent")
        if isinstance(item, (list, tuple, dict)):
            raise ValueError("pick_items accepts exactly one item")
        if order_id is None:
            order_id = self.last_picked_order_id
        if order_id is None:
            raise ValueError("pick_items requires an order_id")
        order_obj = self.order_registry.get(order_id)
        if order_obj is None:
            raise ValueError(f"Unknown order: {order_id}")
        self._require_legal_picker_action(
            "pick", {"order_id": order_id, "item": item}
        )
        picked = self.items.setdefault(order_id, {})
        required_quantity = order_obj.items.get(item, 0)
        if len(picked.get(item, [])) >= required_quantity:
            raise ValueError(f"Item quantity already fulfilled for order: {order_id}")
        if inventory.items.get(item, 0) < 1:
            raise ValueError(f"Item is unavailable in inventory: {item}")

        health = inventory.item_health[item][-1]
        inventory.consume_for_pick({item: 1})
        picked.setdefault(item, []).append(health)
        carried = self.carried_items.setdefault(order_id, {})
        carried.setdefault(item, []).append(health)
        queued_actions = self.action_queue.get(order_id, [])
        for index, queued_action in enumerate(queued_actions):
            if queued_action["item"] == item:
                queued_actions.pop(index)
                break
        if not queued_actions:
            self.action_queue.pop(order_id, None)
        if item in self.available_items:
            self.available_items.remove(item)
        if all(
            len(picked.get(required_item, [])) >= quantity
            for required_item, quantity in order_obj.items.items()
        ):
            order_obj.status = "picked"
            self.blocked_orders.pop(order_id, None)
            self.order_queue = [
                queued_order
                for queued_order in self.order_queue
                if queued_order.order_id != order_id
            ]
            self.action_queue.pop(order_id, None)
        else:
            order_obj.status = "on-hold" if order_id in self.blocked_orders else "picking"
        return item, health

    def inventory_refilled(self, actions):
        for action in actions:
            order_id = action.get("order_id")
            if order_id is None:
                continue
            self.action_queue.setdefault(order_id, []).append(action)
            order_obj = self.blocked_orders.pop(order_id, None)
            if order_obj is not None and order_obj not in self.order_queue:
                self.order_queue.append(order_obj)
                order_obj.status = "picking"

    def process_next_action(self):
        if not self.action_queue:
            return None

        order_id = next(
            (order_id for order_id, actions in self.action_queue.items() if actions),
            None,
        )
        if order_id is None:
            return None
        action = self.action_queue[order_id][0]
        self.last_picked_order_id = order_id
        picked = self.pick_items(action["item"], order_id)
        return picked

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}), action.get("timestep", 0)
            )
        self._validate_action_owner(action)
        if action.action_type == "find_items":
            order_id = action.parameters["order_id"]
            order_obj = self.order_registry.get(order_id)
            if order_obj is None:
                order_obj = next(
                    (candidate for candidate in self.order_queue
                     if candidate.order_id == order_id),
                    None,
                )
            if order_obj is None:
                raise ValueError(f"Unknown order: {order_id}")
            self._require_legal_picker_action(
                "find_items", {"order_id": order_id}
            )
            available = self.find_items(order_obj)
            return {"success": True, "action": "find_items", "available": available}
        if action.action_type == "pick":
            self._require_legal_picker_action(
                "pick",
                {
                    "order_id": action.parameters["order_id"],
                    "item": action.parameters["item"],
                },
            )
            picked = self.pick_items(
                action.parameters["item"],
                action.parameters["order_id"],
            )
            return {"success": True, "action": "pick", "picked": picked}
        if action.action_type == "move_to_packer":
            order_id = action.parameters["order_id"]
            order_obj = self.order_registry.get(order_id)
            if order_obj is None:
                raise ValueError(f"Unknown order: {order_id}")
            self._require_legal_picker_action(
                "move_to_packer", {"order_id": order_id}
            )
            self.move_to_packer(order_obj)
            return {"success": True, "action": "move_to_packer"}
        if action.action_type == "unload_to_packer":
            order_id = action.parameters["order_id"]
            order_obj = self.order_registry.get(order_id)
            if order_obj is None:
                raise ValueError(f"Unknown order: {order_id}")
            self._require_legal_picker_action(
                "unload_to_packer", {"order_id": order_id}
            )
            self.unload_to_packer(order_obj)
            return {"success": True, "action": "unload_to_packer"}
        return super().execute_action(action, state)

    def advance_timestep(self):
        return self.process_next_action()

    def move_to_packer(self, items):
        return self.unload_to_packer(items, require_complete=True)

    def unload_to_packer(self, items, require_complete=False):
        packers = self._connected_packers()
        if not packers:
            raise RuntimeError("Picker is not connected to a packer agent")

        order_obj = items if hasattr(items, "order_id") else None
        if order_obj is None and self.order_queue:
            order_obj = self.order_queue[0]
        if order_obj is None:
            raise ValueError("move_to_packer requires an order")
        action_type = "move_to_packer" if require_complete else "unload_to_packer"
        self._require_legal_picker_action(
            action_type, {"order_id": order_obj.order_id}
        )
        picked = self.items.get(order_obj.order_id, {})
        carried = self.carried_items.get(order_obj.order_id, {})
        if require_complete and not all(
            len(picked.get(item, [])) >= quantity
            for item, quantity in order_obj.items.items()
        ):
            raise ValueError(f"Order is not fully picked: {order_obj.order_id}")
        if not carried:
            raise ValueError(f"No carried items for order: {order_obj.order_id}")
        linked_orders = self.neighboring_agents if isinstance(
            self.neighboring_agents, dict
        ) else {}
        packer = next(
            (
                agent
                for agent in packers
                if any(
                    linked_order is order_obj
                    or (
                        isinstance(linked_order, dict)
                        and linked_order.get("order_id") == order_obj.order_id
                    )
                    for linked_order in linked_orders.get(agent, [])
                )
            ),
            packers[0],
        )
        package = {
            "order_id": order_obj.order_id,
            "order": order_obj,
            "items": {
                item: list(healths) for item, healths in carried.items()
            },
        }
        order_obj.status = "packing" if not require_complete else "packing"
        packer.order_queue.append(package)
        if isinstance(self.neighboring_agents, dict):
            self.neighboring_agents.setdefault(packer, []).append(package)
        self.carried_items.pop(order_obj.order_id, None)
        if all(
            len(picked.get(item, [])) >= quantity
            for item, quantity in order_obj.items.items()
        ):
            self.order_queue = [
                queued_order
                for queued_order in self.order_queue
                if queued_order.order_id != order_obj.order_id
            ]
            self.action_queue.pop(order_obj.order_id, None)
            self.blocked_orders.pop(order_obj.order_id, None)
        else:
            order_obj.status = "picking"
        return packer

    def wait(self):
        self.state = "wait"
        return True



class PackerAgent(AgentProtocol):
    def __init__(self, packer_id, package_capacity, order_queue=None, packages=None, neighboring_agents=None, model=None):
        self.packer_id = packer_id
        self.package_capacity = package_capacity  # Maximum number of packages the packer can handle
        self.order_queue = [] if order_queue is None else order_queue
        self.packages = [] if packages is None else packages
        self.neighboring_agents = [] if neighboring_agents is None else neighboring_agents
        self.state = "available"
        self.model = model

    def _dispatch_agents(self):
        return [
            agent for agent in self._neighbor_list()
            if isinstance(agent, DispatchAgent)
        ]

    def _package_remaining(self, package):
        order_obj = package.get("order")
        if order_obj is None:
            return {}
        return {
            item: max(
                quantity - len(package.get("items", {}).get(item, [])),
                0,
            )
            for item, quantity in order_obj.items.items()
            if quantity > len(package.get("items", {}).get(item, []))
        }

    def _is_complete(self, package):
        return not self._package_remaining(package)

    def _is_legal_action(self, action_type, order_id=None):
        if action_type == "wait":
            return True, ""
        if action_type == "accept_package":
            package = next(
                (
                    package for package in self.order_queue
                    if package.get("order_id") == order_id
                ),
                None,
            )
            if package is None:
                return False, f"Unknown incoming package: {order_id}"
            existing = next(
                (
                    package for package in self.packages
                    if package.get("order_id") == order_id
                ),
                None,
            )
            if existing is None and len(self.packages) >= self.package_capacity:
                return False, "Packer capacity exceeded"
            return True, ""
        if action_type == "move_to_dispatch":
            package = next(
                (
                    package for package in self.packages
                    if package.get("order_id") == order_id
                ),
                None,
            )
            if package is None:
                return False, f"Unknown package: {order_id}"
            if package.get("status") != "packed":
                return False, "Only packed packages can move to dispatch"
            if not self._dispatch_agents():
                return False, "Packer is not connected to dispatch"
            return True, ""
        return False, f"Unsupported packer action: {action_type}"

    def available_actions(self):
        actions = [
            {
                "action_type": "accept_package",
                "parameters": {"order_id": package["order_id"]},
            }
            for package in self.order_queue
            if self._is_legal_action(
                "accept_package", package["order_id"]
            )[0]
        ]
        actions.extend(
            {
                "action_type": "move_to_dispatch",
                "parameters": {"order_id": package["order_id"]},
            }
            for package in self.packages
            if self._is_legal_action(
                "move_to_dispatch", package["order_id"]
            )[0]
        )
        actions.append({"action_type": "wait", "parameters": {}})
        return actions

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update(
            {
                "package_capacity": self.package_capacity,
                "incoming_packages": [
                    {
                        "order_id": package["order_id"],
                        "items": {
                            item: list(healths)
                            for item, healths in package.get("items", {}).items()
                        },
                    }
                    for package in self.order_queue
                ],
                "packages": [
                    {
                        "order_id": package["order_id"],
                        "status": package.get("status"),
                        "items": {
                            item: list(healths)
                            for item, healths in package.get("items", {}).items()
                        },
                        "remaining_items": self._package_remaining(package),
                    }
                    for package in self.packages
                ],
                "dispatch_available": bool(self._dispatch_agents()),
                "action_mask": self.available_actions(),
            }
        )
        return observation

    def pack_items(self, items):
        if not isinstance(items, dict) or "order_id" not in items:
            raise ValueError("Package must contain an order_id")
        order_id = items["order_id"]
        existing = next(
            (package for package in self.packages
             if package["order_id"] == order_id),
            None,
        )
        if existing is None:
            known_order_ids = {
                package["order_id"] for package in self.packages
            }
            if len(known_order_ids) >= self.package_capacity:
                raise ValueError("Packer capacity exceeded")
            package = {
                "order_id": order_id,
                "order": items.get("order"),
                "items": {},
            }
            self.packages.append(package)
        else:
            package = existing

        for item, healths in items.get("items", {}).items():
            package.setdefault("items", {}).setdefault(item, []).extend(healths)

        order_obj = items.get("order")
        if order_obj is None:
            order_obj = package.get("order")
        if order_obj is not None:
            package["order"] = order_obj
        complete = order_obj is not None and all(
            len(package.get("items", {}).get(item, [])) >= quantity
            for item, quantity in order_obj.items.items()
        )
        if order_obj is not None:
            order_obj.status = "packed" if complete else "picking"
        package["status"] = "packed" if complete else "accumulating"
        self.state = "available" if complete else "packing"
        return package

    def move_to_dispatch(self, packages):
        dispatch = next(
            (agent for agent in self._neighbor_list()
             if isinstance(agent, DispatchAgent)),
            None,
        )
        if dispatch is None:
            raise RuntimeError("Packer is not connected to a dispatch agent")
        for package in packages if isinstance(packages, list) else [packages]:
            if package not in self.packages or package.get("status") != "packed":
                raise ValueError("Only packed packages can move to dispatch")
            dispatch.order_queue.append(package)
            self.packages.remove(package)
        self.state = "available"
        return dispatch

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}),                 action.get("timestep", 0)
            )
        self._validate_action_owner(action)
        if action.action_type == "accept_package":
            order_id = action.parameters["order_id"]
            package = next(
                (candidate for candidate in self.order_queue
                 if candidate["order_id"] == order_id),
                None,
            )
            if package is None:
                raise ValueError(f"Unknown package: {order_id}")
            legal, reason = self._is_legal_action(
                "accept_package", order_id
            )
            if not legal:
                raise ValueError(reason)
            self.pack_items(package)
            self.order_queue.remove(package)
            return {"success": True, "action": "accept_package"}
        if action.action_type == "move_to_dispatch":
            order_id = action.parameters.get("order_id")
            if order_id is None:
                raise ValueError("move_to_dispatch requires an order_id")
            legal, reason = self._is_legal_action(
                "move_to_dispatch", order_id
            )
            if not legal:
                raise ValueError(reason)
            packages = [
                package for package in self.packages
                if package["order_id"] == order_id
            ]
            self.move_to_dispatch(packages)
            return {"success": True, "action": "move_to_dispatch"}
        return super().execute_action(action, state)
    def wait(self):
        #wait until the dispatch is ready or no action is needed ie there is no new orders.
        return True



class DispatchAgent(AgentProtocol):
    def __init__(self, dispatch_id, delivery_capacity, order_queue=None, deliveries=None, neighboring_agents=None, model=None):
        self.dispatch_id = dispatch_id
        self.delivery_capacity = delivery_capacity  # Maximum number of deliveries the dispatch can handle
        self.dispatch_capacity = delivery_capacity
        self.order_queue = [] if order_queue is None else order_queue  # Queue of orders assigned to the dispatch(only item list of the order is assigned to the dispatch agent, not the whole order object)
        self.deliveries = [] if deliveries is None else deliveries  # List of deliveries to be made (only item list of the order is assigned to the dispatch agent, not the whole order object)
        self.neighboring_agents = {} if neighboring_agents is None else neighboring_agents  # Neighboring agents mapped to their order queues
        self.model = model

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update(
            {
                "delivery_capacity": self.delivery_capacity,
                "outbound_queue": [
                    package["order_id"]
                    for package in self.order_queue
                    if not self._is_return_route(package)
                ],
                "return_queue": [
                    package["order_id"]
                    for package in self.order_queue
                    if self._is_return_route(package)
                ],
                "connected_delivery_agents": [
                    {
                        "delivery_id": agent.delivery_id,
                        "state": agent.state,
                        "capacity_remaining": (
                            agent.delivery_capacity
                            - len(agent.order_queue)
                            - (1 if agent.current_delivery is not None else 0)
                        ),
                    }
                    for agent in self._delivery_agents()
                ],
                "action_mask": self.available_actions(),
            }
        )
        return observation

    def _has_delivery_capacity(self, count=1):
        return any(
            agent.state in {"available", "wait"}
            and len(agent.order_queue) + count <= agent.delivery_capacity
            for agent in self._delivery_agents()
        )

    def _route_exists(self, order_id, return_request=False):
        payloads = list(self.deliveries)
        payloads.extend(
            package
            for agent in self._delivery_agents()
            for package in agent.order_queue
        )
        payloads.extend(
            [agent.current_delivery]
            for agent in self._delivery_agents()
            if agent.current_delivery is not None
        )
        return any(
            payload.get("order_id") == order_id
            and self._is_return_route(payload) == return_request
            for payload in payloads
        )

    def available_actions(self):
        actions = [
            {
                "action_type": "assign_delivery",
                "parameters": {"order_id": package["order_id"]},
            }
            for package in self.order_queue
            if (
                not self._is_return_route(package)
                and package.get("status") == "packed"
                and self._has_delivery_capacity()
            )
        ]
        actions.extend(
            {
                "action_type": "assign_return",
                "parameters": {"order_id": package["order_id"]},
            }
            for package in self.order_queue
            if (
                self._is_return_route(package)
                and self._has_delivery_capacity()
            )
        )
        actions.append({"action_type": "wait", "parameters": {}})
        return actions

    def _delivery_agents(self):
        return [
            agent for agent in self._neighbor_list()
            if isinstance(agent, DeliveryAgent)
        ]

    def assign_returns(self, return_requests):
        requests = (
            return_requests
            if isinstance(return_requests, list)
            else [return_requests]
        )
        for request in requests:
            if request not in self.order_queue:
                raise ValueError("Unknown return request")
            if not self._is_return_route(request):
                raise ValueError("Only return requests can be assigned")
            if self._route_exists(request["order_id"], return_request=True):
                raise ValueError("Return request has already been routed")
        delivery_agents = self._delivery_agents()
        if not delivery_agents:
            raise RuntimeError("Dispatch is not connected to a delivery agent")
        delivery_agent = next(
            (
                agent for agent in delivery_agents
                if agent.state in {"available", "wait"}
                and len(agent.order_queue) + len(requests)
                <= agent.delivery_capacity
            ),
            None,
        )
        if delivery_agent is None:
            raise ValueError("No delivery agent has capacity")
        for request in requests:
            self.order_queue.remove(request)
            request["status"] = "return_assigned"
            request["route_type"] = "return"
        delivery_agent.deliver_packages(requests)
        self.deliveries.extend(requests)
        return delivery_agent
    def assign_delivery(self, packages):
        deliveries = packages if isinstance(packages, list) else [packages]
        for package in deliveries:
            if package not in self.order_queue:
                raise ValueError("Unknown dispatch package")
            if package.get("status") != "packed":
                raise ValueError("Only packed packages can be assigned")
            if self._route_exists(package["order_id"]):
                raise ValueError("Package has already been routed")
        delivery_agents = self._delivery_agents()
        if not delivery_agents:
            raise RuntimeError("Dispatch is not connected to a delivery agent")
        delivery_agent = next(
            (
                agent for agent in delivery_agents
                if agent.state in {"available", "wait"}
                and len(agent.order_queue) + len(deliveries)
                <= agent.delivery_capacity
            ),
            None,
        )
        if delivery_agent is None:
            raise ValueError("No delivery agent has capacity")
        for package in deliveries:
            self.order_queue.remove(package)
            package["status"] = "dispatched"
            package["route_type"] = "outbound"
        delivery_agent.deliver_packages(deliveries)
        self.deliveries.extend(deliveries)
        return delivery_agent

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}), action.get("timestep", 0)
            )
        self._validate_action_owner(action)
        if action.action_type == "assign_delivery":
            order_id = action.parameters["order_id"]
            package = next(
                (
                    candidate for candidate in self.order_queue
                    if candidate.get("order_id") == order_id
                ),
                None,
            )
            if package is None:
                raise ValueError(f"Unknown dispatch package: {order_id}")
            self.assign_delivery(package)
            return {"success": True, "action": "assign_delivery"}
        if action.action_type == "assign_return":
            order_id = action.parameters["order_id"]
            request = next(
                (
                    candidate for candidate in self.order_queue
                    if candidate.get("order_id") == order_id
                    and self._is_return_route(candidate)
                ),
                None,
            )
            if request is None:
                raise ValueError(f"Unknown return request: {order_id}")
            self.assign_returns(request)
            return {"success": True, "action": "assign_return"}
        return super().execute_action(action, state)
    def wait(self):
        #wait until the delivery agent is ready or no action is needed ie there is no new orders.
        return True



class DeliveryAgent(AgentProtocol):
    def __init__(self, delivery_id, delivery_capacity, order_queue=None, deliveries=None, neighboring_agents=None, model=None):
        self.delivery_id = delivery_id
        self.delivery_capacity = delivery_capacity  # Maximum number of deliveries the delivery agent can handle
        self.order_queue = [] if order_queue is None else order_queue
        self.deliveries = [] if deliveries is None else deliveries
        self.neighboring_agents = [] if neighboring_agents is None else neighboring_agents
        self.state = "wait"
        self.current_delivery = None
        self.travel_remaining = 0
        self.route_started = False
        self.model = model

    def available_actions(self):
        actions = []
        if self.current_delivery is None:
            actions.extend(
                {
                    "action_type": "accept_delivery",
                    "parameters": {"order_id": package.get("order_id")},
                }
                for package in self.order_queue
            )
        elif not self.route_started:
            actions.append({
                "action_type": "travel_to_customer",
                "parameters": {"duration": 1},
            })
        elif self.travel_remaining > 0:
            pass
        else:
            actions.append({
                "action_type": "deliver_order",
                "parameters": {},
            })
        actions.append({"action_type": "wait", "parameters": {}})
        return actions

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update({
            "delivery_capacity": self.delivery_capacity,
            "queue": [
                {
                    "order_id": package.get("order_id"),
                    "route_type": package.get(
                        "route_type",
                        "return"
                        if self._is_return_route(package)
                        else "outbound",
                    ),
                }
                for package in self.order_queue
            ],
            "current_delivery": (
                None
                if self.current_delivery is None
                else {
                    "order_id": self.current_delivery.get("order_id"),
                    "route_type": self.current_delivery.get(
                        "route_type",
                        "return"
                        if self._is_return_route(self.current_delivery)
                        else "outbound",
                    ),
                }
            ),
            "travel_remaining": self.travel_remaining,
            "action_mask": self.available_actions(),
        })
        return observation

    def deliver_packages(self, packages):
        if len(self.order_queue) + len(packages) > self.delivery_capacity:
            raise ValueError("Delivery capacity exceeded")
        self.order_queue.extend(packages)
        return len(packages)

    def _return_evaluation_agents(self):
        return [
            agent for agent in self._neighbor_list()
            if isinstance(agent, ReturnEvaluationAgent)
        ]

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}), action.get("timestep", 0)
            )
        self._validate_action_owner(action)
        if action.action_type == "accept_delivery":
            if self.current_delivery is not None:
                raise ValueError("Delivery agent is already carrying a delivery")
            order_id = action.parameters["order_id"]
            package = next(
                (candidate for candidate in self.order_queue
                 if candidate.get("order_id") == order_id),
                None,
            )
            if package is None:
                raise ValueError(f"Unknown delivery package: {order_id}")
            self.order_queue.remove(package)
            self.current_delivery = package
            package["status"] = "in_transit"
            self.route_started = False
            self.state = "on-route"
            return {"success": True, "action": "accept_delivery"}
        if action.action_type == "travel_to_customer":
            if self.current_delivery is None:
                raise ValueError("No delivery is assigned")
            if self.route_started:
                raise ValueError("Delivery agent has already started this route")
            self.travel_remaining = max(
                int(action.parameters.get("duration", 1)), 1
            )
            self.route_started = True
            self.state = "on-route"
            return {"success": True, "action": "travel_to_customer"}
        if action.action_type == "deliver_order":
            if self.current_delivery is None:
                raise ValueError("No delivery is assigned")
            if not self.route_started:
                raise ValueError("Delivery agent has not started the route")
            if self.travel_remaining > 0:
                raise ValueError("Delivery agent has not reached the customer")
            order_obj = self.current_delivery.get("order")
            if self._is_return_route(self.current_delivery):
                return_agents = self._return_evaluation_agents()
                if not return_agents:
                    raise RuntimeError(
                        "Delivery agent is not connected to return evaluation"
                    )
                if order_obj is not None:
                    order_obj.status = "return_in_transit"
                self.current_delivery["status"] = "return_delivered"
                return_agents[0].order_queue.append(self.current_delivery)
            elif order_obj is not None:
                order_obj.status = "completed"
                self.current_delivery["status"] = "delivered"
            self.deliveries.append(self.current_delivery)
            self.current_delivery = None
            self.route_started = False
            self.state = "wait"
            return {"success": True, "action": "deliver_order", "done": True}
        return super().execute_action(action, state)

    def wait(self):
        if self.travel_remaining > 0:
            self.travel_remaining -= 1
        self.state = "wait" if self.current_delivery is None else "on-route"
        return True



class InventoryAgent(AgentProtocol):
    def __init__(
        self,
        inventory_id,
        items=None,
        neighboring_agents=None,
        refill_delay=2,
        model=None,
        predictive_refill_model=None,
    ):
        if refill_delay < 0:
            raise ValueError("Refill delay cannot be negative")
        self.inventory_id = inventory_id
        # Aggregate stock by item and the corresponding per-unit health stack.
        self.items = {}
        self.item_health = {}
        self.inventory = self.items
        self.item_inventory = self.item_health
        self.neighboring_agents = [] if neighboring_agents is None else neighboring_agents
        self.pending_orders = []
        self.waiting_pickers = {}
        self.simulation_time = 0
        self.refill_delay = refill_delay
        self.notifications = []
        self.model = model
        if predictive_refill_model is None:
            from backend.model.predictive_refill import (
                PlaceholderPredictiveRefillModel,
            )

            predictive_refill_model = PlaceholderPredictiveRefillModel()
        self.predictive_refill_model = predictive_refill_model
        if items is not None:
            self.update_inventory(items, "add")
        self.initialize_predictive_refill()

    @staticmethod
    def _item_quantities(items):
        if isinstance(items, dict):
            return list(items.items())
        return [(item, 1) for item in items]

    def _add_item(self, item, quantity, health=1.0):
        if quantity <= 0:
            raise ValueError("Item quantity must be positive")
        self.items[item] = self.items.get(item, 0) + quantity
        self.item_health.setdefault(item, []).extend([health] * quantity)

    @staticmethod
    def _health_ratio(health):
        return health / 100 if health > 1 else health

    def get_inventory(self):
        return dict(self.items)

    def get_item_inventory(self):
        return {
            item: list(health_stack)
            for item, health_stack in self.item_health.items()
        }

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update(
            {
                "inventory": self.get_inventory(),
                "item_inventory": self.get_item_inventory(),
                "pending_refills": [
                    {
                        "items": dict(refill["items"]),
                        "ready_at": refill["ready_at"],
                    }
                    for refill in self.pending_orders
                ],
                "waiting_pickers": {
                    item: [
                        {
                            "order_id": request["order_id"],
                            "quantity": request["quantity"],
                        }
                        for request in requests
                    ]
                    for item, requests in self.waiting_pickers.items()
                },
                "simulation_time": self.simulation_time,
                "action_mask": self.available_actions(),
            }
        )
        return observation

    def available_actions(self):
        actions = []
        pending_items = {
            item
            for refill in self.pending_orders
            for item in refill["items"]
        }
        refill_quantities = {}
        for item, requests in self.waiting_pickers.items():
            if item not in pending_items:
                refill_quantities[item] = sum(
                    request["quantity"] for request in requests
                )
        actions.extend(
            {
                "action_type": "refill",
                "parameters": {"items": {item: quantity}},
            }
            for item, quantity in refill_quantities.items()
            if quantity > 0
        )
        actions.append(
            {
                "action_type": "wait",
                "parameters": {"simulation_time": 1},
            }
        )
        return actions

    def check_availability(self, items, picker=None, order_id=None):
        available = []
        unavailable = []
        scheduled = self._scheduled_quantities()
        for item, quantity in self._item_quantities(items):
            stock = self.items.get(item, 0)
            available_quantity = min(stock, quantity)
            available.extend([item] * available_quantity)
            if available_quantity < quantity:
                unavailable.append((item, quantity - available_quantity))

        if unavailable:
            if picker is not None:
                for item, quantity in unavailable:
                    waiting = self.waiting_pickers.setdefault(item, [])
                    existing = next(
                        (
                            request for request in waiting
                            if request["order_id"] == order_id
                            and request["picker"] is picker
                        ),
                        None,
                    )
                    if existing is None:
                        waiting.append(
                            {
                                "order_id": order_id,
                                "picker": picker,
                                "quantity": quantity,
                            }
                        )
            refill = {
                item: max(quantity - scheduled.get(item, 0), 0)
                for item, quantity in unavailable
                if quantity > scheduled.get(item, 0)
            }
            if refill:
                self.place_order(refill, simulation_time=self.refill_delay)
        return available

    def _scheduled_quantities(self):
        scheduled = {}
        for refill in self.pending_orders:
            for item, quantity in refill["items"].items():
                scheduled[item] = scheduled.get(item, 0) + quantity
        return scheduled

    def initialize_predictive_refill(self):
        """Run the startup forecast after all inventory models are connected."""
        return self.predictive_refill()

    def predictive_refill(self, items=None):
        """Forecast and schedule only stock not already available or pending."""
        if items is None:
            observation = {
                "inventory": self.get_inventory(),
                "item_inventory": self.get_item_inventory(),
                "pending_refills": [
                    {
                        "items": dict(refill["items"]),
                        "ready_at": refill["ready_at"],
                    }
                    for refill in self.pending_orders
                ],
                "simulation_time": self.simulation_time,
            }
            items = self.predictive_refill_model.forecast(observation)
        recommendations = dict(self._item_quantities(items))
        scheduled = self._scheduled_quantities()
        refill = {
            item: max(
                quantity - self.items.get(item, 0) - scheduled.get(item, 0),
                0,
            )
            for item, quantity in recommendations.items()
        }
        refill = {item: quantity for item, quantity in refill.items() if quantity}
        if refill:
            self.place_order(refill, simulation_time=self.refill_delay)
        return refill

    def update_inventory(self, items, action):
        #update the inventory based on the action performed by the picker agent or any other agent that affects the inventory.
        action = action.lower()
        if action in {"add", "refill", "return", "returned"}:
            for item, value in self._item_quantities(items):
                if isinstance(value, list):
                    for health in value:
                        if isinstance(health, tuple):
                            quantity, unit_health = health
                        else:
                            quantity, unit_health = 1, health
                        self._add_item(item, quantity, unit_health)
                elif isinstance(value, tuple):
                    quantity, health = value
                    self._add_item(item, quantity, health)
                else:
                    self._add_item(item, value, 1.0)
        elif action in {"remove", "pick", "picked", "consume"}:
            for item, quantity in self._item_quantities(items):
                if self.items.get(item, 0) < quantity:
                    raise ValueError(f"Insufficient inventory for item: {item}")
            for item, quantity in self._item_quantities(items):
                self.items[item] -= quantity
                del self.item_health[item][-quantity:]
        else:
            raise ValueError(f"Unsupported inventory action: {action}")
        return dict(self.items)

    def consume_for_pick(self, items):
        """Consume stock for a picker operation owned by the PickerAgent."""
        return self.update_inventory(items, "pick")

    def place_order(self, items, simulation_time=0):
        #place an order for invetory refill based on the items that are unavailable in the inventory and return a list of items that are ordered for refill.
        #this function will take some time in simulation to make ot look like an actual inventory refill order is placed and the items are restocked in the inventory after some time.
        #this will be a rl based predictive refill system that will predict the items that are likely to be ordered in the future based on the current orders and the historical data of the orders and the inventory levels and the weather conditions and the time of the day and the malicious factors affecting the simulation.
        if simulation_time < 0:
            raise ValueError("Simulation time cannot be negative")
        refill = dict(self._item_quantities(items))
        if simulation_time == 0:
            self.update_inventory(refill, "refill")
            self._notify_waiting_pickers(refill)
        else:
            self.pending_orders.append(
                {"items": refill, "ready_at": self.simulation_time + simulation_time}
            )
        return refill

    def _notify_waiting_pickers(self, items):
        for item, quantity in items.items():
            waiting = self.waiting_pickers.get(item, [])
            remaining = []
            scheduled = 0
            for request in waiting:
                available = self.items.get(item, 0) - scheduled
                if available <= 0:
                    remaining.append(request)
                    continue

                quantity_to_schedule = min(
                    request["quantity"], quantity, available
                )
                actions = [
                    {"item": item, "order_id": request["order_id"]}
                    for _ in range(quantity_to_schedule)
                ]
                picker = request["picker"]
                if hasattr(picker, "inventory_refilled"):
                    picker.inventory_refilled(actions)
                scheduled += quantity_to_schedule
                self.notifications.extend(actions)

                if quantity_to_schedule < request["quantity"]:
                    remaining.append(
                        {
                            **request,
                            "quantity": request["quantity"] - quantity_to_schedule,
                        }
                    )

            if remaining:
                self.waiting_pickers[item] = remaining
            else:
                self.waiting_pickers.pop(item, None)

    def wait(self, simulation_time=0):
        #wait when no action is needed ie there is no new orders.
        if simulation_time < 0:
            raise ValueError("Simulation time cannot be negative")
        self.simulation_time += simulation_time
        completed = []
        remaining = []
        for order in self.pending_orders:
            if order["ready_at"] <= self.simulation_time:
                self.update_inventory(order["items"], "refill")
                self._notify_waiting_pickers(order["items"])
                completed.append(order["items"])
            else:
                remaining.append(order)
        self.pending_orders = remaining
        if completed:
            self.predictive_refill()
        return completed

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}), action.get("timestep", 0)
            )
        self._validate_action_owner(action)
        if action.action_type == "refill":
            items = action.parameters["items"]
            self.place_order(items, action.parameters.get("delay", self.refill_delay))
            return {"success": True, "action": "refill"}
        if action.action_type == "pick":
            self.consume_for_pick(action.parameters["items"])
            return {"success": True, "action": "pick"}
        if action.action_type == "wait":
            duration = action.parameters.get("simulation_time", 1)
            if state is not None:
                target_time = state.time + 1
                duration = max(target_time - self.simulation_time, 0)
            completed = self.wait(duration)
            return {
                "success": True,
                "action": "wait",
                "completed_refills": completed,
            }
        return super().execute_action(action, state)

    def handle_returned_items(self, items):
        #handle the returned items from the customers and update the inventory based on  the returned items evaluator agent.
        for item, value in self._item_quantities(items):
            if isinstance(value, tuple):
                quantity, health = value
            else:
                quantity, health = value, 1.0
            self._add_item(item, quantity, health)
        return dict(self.items)



class ReturnEvaluationAgent(AgentProtocol):
    def __init__(
        self,
        return_evaluation_id,
        neighboring_agents=None,
        model=None,
        restock_health_threshold=0.5,
    ):
        self.return_evaluation_id = return_evaluation_id
        self.neighboring_agents = [] if neighboring_agents is None else neighboring_agents
        self.order_queue = []
        self.model = model
        self.restock_health_threshold = restock_health_threshold
        self.return_history = {}
        self.trust_scores = {}

    def available_actions(self):
        actions = [
            {
                "action_type": "evaluate_return",
                "parameters": {"order_id": request["order_id"]},
            }
            for request in self.order_queue
        ]
        actions.append({"action_type": "wait", "parameters": {}})
        return actions

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update(
            {
                "return_requests": [
                    request["order_id"] for request in self.order_queue
                ],
                "restock_health_threshold": self.restock_health_threshold,
                "action_mask": self.available_actions(),
            }
        )
        return observation
    def assess_trust_score_of_costomer(self, customer_id):
        returns = self.return_history.get(customer_id, 0)
        score = max(0.0, min(1.0, 1.0 / (1.0 + returns)))
        self.trust_scores[customer_id] = score
        return score
    def evaluate_returned_items(self, items):
        #evaluate the returned items from the customers and determine if they can be restocked in the inventory or need to be disposed of based on the condition of the items and the return policy of the system.
        inventory = next(
            (
                agent for agent in self._neighbor_list()
                if isinstance(agent, InventoryAgent)
            ),
            None,
        )
        if inventory is None:
            raise RuntimeError(
                "Return evaluation is not connected to inventory"
            )
        restock = {}
        discarded = {}
        for item, value in inventory._item_quantities(items):
            if isinstance(value, tuple):
                quantity, health = value
            else:
                quantity, health = value, 1.0
            target = (
                restock
                if InventoryAgent._health_ratio(health)
                >= self.restock_health_threshold
                else discarded
            )
            target[item] = (quantity, health)
        if restock:
            inventory.handle_returned_items(restock)
        return {"restocked": restock, "discarded": discarded}

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"], action["action_type"],
                action.get("parameters", {}),
                action.get("timestep", 0),
            )
        self._validate_action_owner(action)
        if action.action_type == "evaluate_return":
            order_id = action.parameters["order_id"]
            request = next(
                (
                    candidate for candidate in self.order_queue
                    if candidate["order_id"] == order_id
                ),
                None,
            )
            if request is None:
                raise ValueError(f"Unknown return request: {order_id}")
            order_obj = request.get("order")
            returned_items = request.get(
                "items",
                {
                    item: (quantity, 1.0)
                    for item, quantity in order_obj.items.items()
                }
                if order_obj is not None
                else {},
            )
            result = self.evaluate_returned_items(returned_items)
            self.order_queue.remove(request)
            if order_obj is not None:
                order_obj.status = "returned"
                customer_id = order_obj.customer_name
                self.return_history[customer_id] = (
                    self.return_history.get(customer_id, 0) + 1
                )
                self.assess_trust_score_of_costomer(customer_id)
            return {
                "success": True,
                "action": "evaluate_return",
                **result,
            }
        return super().execute_action(action, state)
    def wait(self):
        #wait until the inventory agent is ready or no action is needed ie there is no new orders.
        return True



class CustomerAgent(AgentProtocol):#this is a pseudo agent that will input the oeder into the system
    def __init__(self, customer_id, order_requests=None, neighboring_agents=None):
        self.customer_id = customer_id
        self.state = "wait"
        self.order_requests = [] if order_requests is None else order_requests
        self.pending_requests = list(self.order_requests)
        self.received_orders = []
        self.neighboring_agents = [] if neighboring_agents is None else neighboring_agents

    def observe(self, state=None):
        observation = super().observe(state)
        observation.update({
            "state": "wait",
            "pending_requests": len(self.pending_requests),
            "received_orders": [
                {
                    "order_id": received.order_id,
                    "status": received.status,
                }
                for received in self.received_orders
            ],
            "action_mask": self.available_actions(),
        })
        return observation

    def available_actions(self):
        actions = [
            {
                "action_type": "submit_order",
                "parameters": {"order_request": request},
            }
            for request in self.pending_requests
        ]
        actions.extend(
            {
                "action_type": "request_return",
                "parameters": {"order_id": received.order_id},
            }
            for received in self.received_orders
            if received.status == "completed"
        )
        actions.append({"action_type": "wait", "parameters": {}})
        return actions

    def place_order_request(self, order_request):
        if not isinstance(order_request, orderRequest):
            raise TypeError("Customer orders must be orderRequest instances")
        managers = [
            agent for agent in self._neighbor_list()
            if isinstance(agent, OrderManagementAgent)
        ]
        if not managers:
            raise RuntimeError(
                "Customer is not connected to order management"
            )
        self.order_requests.append(order_request)
        if order_request in self.pending_requests:
            self.pending_requests.remove(order_request)
        return managers[0].process_order_request(order_request)

    def recieve_order(self, order):
        if not hasattr(order, "order_id"):
            raise TypeError("Customer can only receive an order object")
        if order not in self.received_orders:
            self.received_orders.append(order)
        return order

    def receive_order(self, order):
        return self.recieve_order(order)

    def return_items(self, items=None, order_id=None):
        order_obj = next(
            (
                received for received in reversed(self.received_orders)
                if (
                    order_id is None or received.order_id == order_id
                )
                and received.status == "completed"
            ),
            None,
        )
        if order_obj is None:
            raise ValueError("Customer has no completed order to return")
        managers = [
            agent for agent in self._neighbor_list()
            if isinstance(agent, OrderManagementAgent)
        ]
        if not managers:
            raise RuntimeError(
                "Customer is not connected to order management"
            )
        if items is None:
            health = getattr(order_obj, "health", {})
            items = {
                item: (quantity, health.get(item, 1.0))
                for item, quantity in order_obj.items.items()
            }
        return managers[0].accept_return_request(order_obj, items)

    def wait(self):
        return True

    def execute_action(self, action, state=None):
        if isinstance(action, dict):
            action = AgentAction(
                action["agent_id"],
                action["action_type"],
                action.get("parameters", {}),
                action.get("timestep", 0),
            )
        self._validate_action_owner(action)
        if action.action_type == "submit_order":
            request = action.parameters.get("order_request")
            if not isinstance(request, orderRequest):
                raise TypeError("submit_order requires an orderRequest")
            order_obj = self.place_order_request(request)
            return {
                "success": True,
                "action": "submit_order",
                "order_id": order_obj.order_id,
            }
        if action.action_type == "request_return":
            result = self.return_items(
                action.parameters.get("items"),
                action.parameters.get("order_id"),
            )
            return {
                "success": bool(result),
                "action": "request_return",
            }
        return super().execute_action(action, state)

    def _neighbor_list(self):
        return (
            list(self.neighboring_agents.keys())
            if isinstance(self.neighboring_agents, dict)
            else list(self.neighboring_agents)
        )
    #wait for the order.