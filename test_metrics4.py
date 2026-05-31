import sys, time
sys.path.insert(0, 'src')

from chord_dht import ChordRing
from chord_dht.metrics import build_growth_node_sizes, run_lookup_metrics

# First, confirm init is fast
for n in [5, 10, 20, 30, 50]:
    t0 = time.time()
    ring = ChordRing(m=16, seed=61, replication_count=1)
    ring.initialize_network(node_count=n, resource_count=20)
    t1 = time.time()
    print(f"init {n} nodes: {t1-t0:.3f}s")

# Test sweep that was failing before
print("\nTesting full sweep (50 nodes, 2 trials, 50 lookups)...")
t0 = time.time()
result2 = run_lookup_metrics(
    max_node_count=50,
    trial_count=2,
    lookups_per_size=50,
    resource_count=100,
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
