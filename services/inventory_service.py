from agents.inventory import InventoryAgent

class InventoryService:

    def __init__(self):
        self.agent = InventoryAgent(data_path="data_base")

    def evaluate_production(self, finished_product_id, quantity_to_produce):
        return self.agent.evaluate_production(
            finished_product_id=finished_product_id,
            quantity_to_produce=quantity_to_produce
        )
