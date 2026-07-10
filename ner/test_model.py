import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ner.models import load_model

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_model.py <model_key>")
        sys.exit(1)
        
    model_key = sys.argv[1]
    print(f"--- Testing {model_key} ---")
    
    try:
        model = load_model(model_key)
        text = "Aspirin is used to treat headache and reduces the risk of heart attack."
        print(f"Input text: {text}")
        entities = model.predict(text)
        print(f"Output entities: {entities}")
        print("--- Test SUCCESS ---")
    except Exception as e:
        print(f"--- Test FAILED: {e} ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
