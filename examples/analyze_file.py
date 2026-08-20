from synoptyk.core import analyze_signal
import json

print("=== FILE ANALYSIS DEMO ===")

with open("sample_data.json", "r") as f:
    data = json.load(f)

result = analyze_signal(data)

print("Analysis complete.")
print("First 5 steps:")
for step in result[:5]:
    print(step)
