# Sensory screen dashboard

The dashboard reads the analysis CSVs directly from `results/`, so it always reflects the latest pipeline output.

From the repository root, run:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000/dashboard/>.

No build step or third-party JavaScript dependencies are required.
