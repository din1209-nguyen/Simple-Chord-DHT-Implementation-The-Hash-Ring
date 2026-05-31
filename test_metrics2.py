import sys, time
sys.path.insert(0, 'src')

from chord_dht import ChordRing
from chord_dht.metrics import build_growth_node_sizes, run_lookup_metrics

# Simulate the API scenario: 10 active nodes, row_limit = min(10, 50)
print("=== API scenario: 10 nodes, row_limit=10, trials=1, lookups=10 ===")
active_nodes = 10
row_count = max(1, min(active_nodes, 50))  # what API computes
node_sizes = build_growth_node_sizes(active_nodes, row_limit=row_count)
print(f"Node sizes: {node_sizes}")
print(f"len(node_sizes) = {len(node_sizes)}")

t0 = time.time()
try:
    result = run_lookup_metrics(
        node_sizes=node_sizes,
        max_node_count=active_nodes,
        trial_count=1,
        lookups_per_size=10,
        resource_count=20,
        m=16,
        seed=61,
        output_path=None,
    )
    t1 = time.time()
    print(f"Done in {t1-t0:.2f}s, points={len(result['points'])}")
    for p in result['points']:
        print(f"  N={p['nodes']}, avg_hops={p['average_hops']}, lookups={p['total_lookups']}")
except Exception as e:
    t1 = time.time()
    print(f"FAILED after {t1-t0:.2f}s: {e}")
    import traceback
    traceback.print_exc()

# Now test with sweep_mode=True (len(node_sizes) >= 20)
print("\n=== Sweep mode: 50 nodes, row_limit=50, trials=5, lookups=100 ===")
t0 = time.time()
try:
    result2 = run_lookup_metrics(
        max_node_count=50,
        trial_count=5,
        lookups_per_size=100,
        resource_count=1000,
        m=16,
        seed=61,
        output_path=None,
    )
    t1 = time.time()
    print(f"Done in {t1-t0:.2f}s, points={len(result2['points'])}")
    for p in result2['points'][:5]:
        print(f"  N={p['nodes']}, avg_hops={p['average_hops']}")
    if len(result2['points']) > 5:
        print(f"  ... ({len(result2['points'])} total)")
except Exception as e:
    t1 = time.time()
    print(f"FAILED after {t1-t0:.2f}s: {e}")
    import traceback
    traceback.print_exc()
