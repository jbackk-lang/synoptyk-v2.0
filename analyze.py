from SYNOPTIC_F import analyze_signal
import sys

def main():
    if len(sys.argv) < 2:
        print("Użycie: python analyze.py dane.csv")
        return

    filename = sys.argv[1]
    print(f"Analiza pliku: {filename}")
    result = analyze_signal(filename)
    print("Wynik analizy:", result)

if __name__ == "__main__":
    main()
