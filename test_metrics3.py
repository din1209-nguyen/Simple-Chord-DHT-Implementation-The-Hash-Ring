import sys, time
sys.path.insert(0, 'src')

from chord_dht import ChordRing

# Test initialize_network for various sizes
for n in [5, 10, 20, 30]:
    t0 = time.time()
    ring = ChordRing(m=16, seed=61, replication_count=1)
    ring.initialize_network(node_count=n, resource_count=20)
    t1 = time.time()
    print(f"init {n} nodes: {t1-t0:.2f}s")

# Test one full protocol round for n=10
print("\nTesting protocol convergence for n=10...")
ring = ChordRing(m=16, seed=61, replication_count=1)
ring.initialize_network(node_count=10, resource_count=20)
t0 = time.time()
ring.run_protocol(rounds=8)
t1 = time.time()
print(f"8 rounds of protocol: {t1-t0:.2f}s")

# Test a single lookup
t0 = time.time()
for i in range(100):
    ring.lookup(f"resource-{i%20+1:04d}")
t1 = time.time()
print(f"100 lookups: {t1-t0:.2f}s")

# Test metrics with 10 node sizes, 1 trial, 10 lookups
print("\nTesting metrics with 10 sizes...")
from chord_dht.metrics import build_growth_node_sizes, run_lookup_metrics
node_sizes = build_growth_node_sizes(10, row_limit=10)
t0 = time.time()
result = run_lookup_metrics(
    node_sizes=node_sizes,
    max_node_count=10,
    trial_count=1,
    lookups_per_size=10,
    resource_count=20,
    m=16,
    seed=61,
    output_path=None,
)
t1 = time.time()
print(f"10 sizes done in {t1-t0:.2f}s, points={len(result['points'])}")
