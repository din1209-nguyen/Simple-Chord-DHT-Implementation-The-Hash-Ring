import sys, time
sys.path.insert(0, 'src')

from chord_dht import ChordRing

print("Testing nc=20, seed=1078, rc=100...", flush=True)
t0 = time.time()
ring = ChordRing(m=16, seed=1078)
try:
    ring.initialize_network(node_count=20, resource_count=100)
    t1 = time.time()
    print(f"OK in {t1-t0:.1f}s", flush=True)
except Exception as e:
    t1 = time.time()
    print(f"FAILED in {t1-t0:.1f}s: {e}", flush=True)
