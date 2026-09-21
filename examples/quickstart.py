"""Minimal durarun example — three steps with crash recovery."""

from durarun import DurableRunner

runner = DurableRunner(backend="sqlite://./demo.db")


@runner.step
def fetch_data(ctx):
    print("Fetching data...")
    return {"items": [1, 2, 3]}


@runner.step(retry=2, timeout="10s")
def process(ctx):
    data = ctx.get("fetch_data")
    total = sum(data["items"])
    print(f"Processing... sum = {total}")
    return {"total": total}


@runner.step
def save_result(ctx):
    result = ctx.get("process")
    print(f"Saving result: {result}")
    return "done"


if __name__ == "__main__":
    result = runner.run([fetch_data, process, save_result])

    print(f"\nRun {result.run_id} completed in {result.total_ms:.1f}ms")
    print(f"Recovered steps: {result.recovered_steps}")
    for detail in result.step_details:
        print(f"  {detail.name}: {detail.source} ({detail.duration_ms:.1f}ms)")
