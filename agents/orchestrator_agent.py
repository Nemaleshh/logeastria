import json
from typing import Dict, Any
import google.generativeai as genai
from execution.orchestration_logger import OrchestrationLogger

class AutonomousOrchestratorAgent:
    def __init__(self, api_key: str, model_name: str = "gemini-3-flash-preview"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.logger = OrchestrationLogger("data_base/orchestration_log.csv")


        self.system_prompt = """
You are the Autonomous Orchestrator Agent of a decentralized AI-driven supply chain system.

STRICT RULES:
- Do NOT calculate quantities.
- Do NOT modify provided numerical values.
- Do NOT invent suppliers.
- Always select the highest confidence supplier available.
- Evaluate each material independently.
- Prioritize resilience over cost.

Return ONLY valid JSON in this format:

{
  "procurement_plan": [
    {
      "material_id": "",
      "selected_supplier": "",
      "quantity_to_order": "",
      "risk_level": "",
      "confidence_level": "",
      "mitigation_strategy": "",
      "reasoning": ""
    }
  ],
  "overall_supply_chain_risk": "",
  "strategic_summary": ""
}
"""

    def run(self, structured_input: Dict[str, Any]) -> Dict[str, Any]:
      prompt = f"""
  SYSTEM:
  {self.system_prompt}

  INPUT DATA:
  {json.dumps(structured_input, indent=2)}

  Analyze and produce final procurement decision.
  Return ONLY valid JSON.
  """

      response = self.model.generate_content(prompt)

      try:
          decision = json.loads(response.text)
      except Exception:
          raise ValueError("Model did not return valid JSON.")

      # -----------------------------
      # 🔥 LOG THE STRATEGIC DECISION
      # -----------------------------
      request_id = self.logger.log(
          product_id=structured_input["production_request"]["order_id"],
          decision_summary=decision.get("strategic_summary"),
          overall_risk=decision.get("overall_supply_chain_risk")
      )

      decision["orchestration_log_id"] = request_id

      return decision
