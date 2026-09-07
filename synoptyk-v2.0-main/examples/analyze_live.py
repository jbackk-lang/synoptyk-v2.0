from synoptyk.core import analyze_signal
import random
import time

print("=== LIVE STREAM DEMO ===")

buffer = []

for _ in range(20):
    value = random.uniform(0.5, 2.0)
    buffer.append(value)

    if len(buffer) > 5:
        result = analyze_signal(buffer[-5:])
        print(result[-1])

    time.sleep(0.2)
