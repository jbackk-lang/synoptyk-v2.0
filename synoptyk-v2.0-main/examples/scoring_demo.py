from synoptyk.scoring import score_prediction
from synoptyk.core import analyze_signal

print("=== SCORING DEMO ===")

true = [1, 0, 1, 1, 0]
pred = [1, 1, 1, 0, 0]

score = score_prediction(true, pred)
print("Score:", score)
