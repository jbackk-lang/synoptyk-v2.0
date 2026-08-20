from synoptyk.core import analyze_signal

data = [1.0, 1.2, 1.5, 1.1, 0.9, 1.3, 1.8]

print("=== BASIC SYNOPTYK DEMO ===")
result = analyze_signal(data)

for step in result:
    print(step)
