from src.llm_arbitrage import ollama_disponible, _call_ollama
print("Ollama disponible:", ollama_disponible())
if ollama_disponible():
    rep = _call_ollama("Reponds uniquement par le chiffre: 2+2=?")
    print("Test reponse LLM:", rep)
