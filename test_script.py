import csv
import os
import time
from pathlib import Path
from collections import defaultdict
import topo
import importlib.util as lib
import matplotlib.pyplot as plt
import numpy as np

RESULTS_CSV = Path("results.csv")

# Test cases for our experiment
SCENARIOS = [
    ("intra_edge",  [("h1", "h2")]),
    ("intra_pod",   [("h1", "h3")]),
    ("inter_pod",   [("h1", "h9")]),
    ("many_to_one", [("h9","h1"),("h10","h1"),("h11","h1"),("h12","h1"),("h13","h1"),("h14","h1")]),
    ("many_to_many",[("h1","h9"),("h2","h10"),("h3","h11"),("h4","h12"),("h5","h13"),("h6","h14"),("h7","h15"),("h8","h16")])
]



def run_mininet_and_test(controller_name):
    results = []

    ft_topo = topo.Fattree(4)
    spec = lib.spec_from_file_location("ft_mod", "./fat-tree.py")
    ft_mod = lib.module_from_spec(spec)
    spec.loader.exec_module(ft_mod)

    net = ft_mod.make_mininet_instance(ft_topo)
    net.start()
    time.sleep(5)

    def host(h): return net.get(h)

    for scenario, pairs in SCENARIOS:
        print(f"\n--- {scenario} ---")

        if scenario in ("intra_edge", "intra_pod", "inter_pod"):
            for src_name, dst_name in pairs:
                src, dst = host(src_name), host(dst_name)

                rtt_ms  = parse_output(src.cmd(f"ping -c 4 {dst.IP()}"), "ping")

                dst.cmd("pkill iperf || true")
                dst.cmd("iperf -s -p 5001 &")
                time.sleep(1)
                thr_mbps = parse_output(src.cmd(f"iperf -c {dst.IP()} -t 5 -p 5001"), "iperf")
                dst.cmd("pkill iperf || true")

                print(f"  {src_name} -> {dst_name}: {thr_mbps:.2f} Mbps, {rtt_ms:.2f} ms")
                results.append({"controller": controller_name, "scenario": scenario,
                                 "pair": f"{src_name}-{dst_name}", "rtt_ms": rtt_ms, "throughput_mbps": thr_mbps})

        elif scenario == "many_to_one":
            dst = host("h1")
            dst.cmd("pkill -9 iperf || true")
            time.sleep(1)
            dst.cmd("iperf -s -p 5001 &")
            time.sleep(2)

            files = []
            for src_name, _ in pairs:
                f = f"/tmp/iperf_{controller_name}_{scenario}_{src_name}.txt"
                files.append(f)
                host(src_name).cmd(f"iperf -c {dst.IP()} -t 5 -p 5001 -y C > {f} 2>&1 &")

            time.sleep(10)

            total, ok = 0.0, 0
            for f in files:
                try:
                    thr = parse_iperf_output(open(f).read())
                    if thr and thr > 0:
                        total += thr
                        ok += 1
                    os.remove(f)
                except Exception as e:
                    print(f"  Error: {e}")

            dst.cmd("pkill iperf || true")
            print(f"  Total: {total:.2f} Mbps ({ok}/{len(pairs)} flows)")
            results.append({"controller": controller_name, "scenario": scenario,
                             "pair": f"*-h1", "rtt_ms": None, "throughput_mbps": total})

        elif scenario == "many_to_many":
            for _, dst_name in pairs:
                host(dst_name).cmd("pkill -9 iperf || true")
            time.sleep(2)

            servers = []
            for idx, (_, dst_name) in enumerate(pairs):
                port = 5001 + idx
                host(dst_name).cmd(f"iperf -s -p {port} 2>&1 &")
                servers.append((dst_name, port))

            # wait for each server to be ready before launching clients
            for dst_name, port in servers:
                for _ in range(20):
                    if host(dst_name).cmd(f"ss -tlnp | grep :{port}").strip():
                        break
                    time.sleep(1)

            files = []
            for idx, (src_name, dst_name) in enumerate(pairs):
                port = 5001 + idx
                f = f"/tmp/iperf_{controller_name}_{scenario}_{src_name}_to_{dst_name}.txt"
                files.append(f)
                host(src_name).cmd(f"iperf -c {host(dst_name).IP()} -t 5 -p {port} -y C > {f} 2>&1 &")

            time.sleep(10)

            total, ok = 0.0, 0
            for idx, f in enumerate(files):
                src_name, dst_name = pairs[idx]
                try:
                    if not os.path.exists(f):
                        print(f"  {src_name}->{dst_name}: no output file")
                        continue
                    content = open(f).read()
                    if "Connection refused" in content or "connect failed" in content.lower():
                        print(f"  {src_name}->{dst_name}: connection failed")
                        continue
                    thr = parse_iperf_output(content)
                    if thr and thr > 0:
                        total += thr
                        ok += 1
                        print(f"  {src_name}->{dst_name}: {thr:.2f} Mbps")
                    else:
                        print(f"  {src_name}->{dst_name}: failed to parse")
                    os.remove(f)
                except Exception as e:
                    print(f"  Error: {e}")

            for dst_name, _ in servers:
                host(dst_name).cmd("pkill -9 iperf || true")

            print(f"  Total: {total:.2f} Mbps ({ok}/{len(pairs)} flows)")
            results.append({"controller": controller_name, "scenario": scenario,
                             "pair": f"{len(pairs)}_flows", "rtt_ms": None, "throughput_mbps": total})

    net.stop()
    return results


def parse_iperf_output(content):
    """Parse iperf CSV or text output and return throughput in Mbps."""
    if not content or not content.strip():
        return None
    for line in content.strip().splitlines():
        if not line.strip():
            continue
        if ',' in line:
            parts = line.split(',')
            if len(parts) >= 9:
                try:
                    bps = float(parts[8])
                    if bps > 0:
                        return bps / 1_000_000.0
                except (ValueError, IndexError):
                    pass
            for part in parts:
                try:
                    val = float(part)
                    if 1_000_000 < val < 100_000_000_000:
                        return val / 1_000_000.0
                except ValueError:
                    pass
    for line in reversed(content.strip().splitlines()):
        if "Mbits/sec" in line:
            parts = line.split()
            try:
                val = float(parts[parts.index("Mbits/sec") - 1])
                if val > 0:
                    return val
            except (ValueError, IndexError):
                pass
    return None

#Parse ping or iperf command output and return the relevant metric.
def parse_output(output, metric):
    if metric == "ping":
        for line in output.splitlines():
            if "rtt min/avg/max/mdev" in line or "round-trip min/avg/max" in line:
                try:
                    return float(line.split("=")[1].strip().split()[0].split('/')[1])
                except Exception:
                    return None
    elif metric == "iperf":
        return parse_iperf_output(output)


def append_results_csv(rows):
    fieldnames = ["controller", "scenario", "pair", "rtt_ms", "throughput_mbps"]
    write_header = not RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


def plot_results():
    buckets = defaultdict(lambda: {"thr": [], "rtt": []})
    with open(RESULTS_CSV, newline='') as f:
        for row in csv.DictReader(f):
            key = (row["controller"], row["scenario"])
            if row["throughput_mbps"] not in ("", "None", None):
                buckets[key]["thr"].append(float(row["throughput_mbps"]))
            if row["rtt_ms"] not in ("", "None", None):
                buckets[key]["rtt"].append(float(row["rtt_ms"]))

    scenarios = [s for s, _ in SCENARIOS]
    x, w = np.arange(len(scenarios)), 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("SP Routing vs Fat-Tree Routing")

    def draw(ax, metric, ylabel):
        sp = [np.mean(buckets[("sp_routing.py", s)][metric] or [0]) for s in scenarios]
        ft = [np.mean(buckets[("ft_routing.py", s)][metric] or [0]) for s in scenarios]
        ax.bar(x - w/2, sp, w, label="SP")
        ax.bar(x + w/2, ft, w, label="FT")
        ax.set_xticks(x)
        ax.set_xticklabels([s.replace("_", " ").title() for s in scenarios], fontsize=9)
        ax.set_ylabel(ylabel)
        ax.legend()

    draw(ax1, "thr", "Throughput (Mbps)")
    draw(ax2, "rtt", "RTT (ms)")

    plt.tight_layout()
    plt.savefig("routing_comparison.png", dpi=150, bbox_inches="tight")
    print("Plot saved: routing_comparison.png")


def main():
    controller_name = input("Enter controller name (sp_routing.py / ft_routing.py): ")
    rows = run_mininet_and_test(controller_name)
    append_results_csv(rows)
    print(f"\nResults written to {RESULTS_CSV}")

    print("\n=== Results Summary ===")
    for row in rows:
        if row['scenario'] in ('many_to_one', 'many_to_many'):
            print(f"{row['scenario']}: {row['throughput_mbps']:.2f} Mbps total")
        else:
            print(f"{row['scenario']} ({row['pair']}): {row['throughput_mbps']:.2f} Mbps, {row['rtt_ms']:.2f} ms")

    if RESULTS_CSV.exists():
        controllers_in_csv = {row["controller"] for row in csv.DictReader(open(RESULTS_CSV))}
        if {"sp_routing.py", "ft_routing.py"}.issubset(controllers_in_csv):
            plot_results()
        else:
            print("\nRun the other controller to generate the comparison plot.")


if __name__ == '__main__':
    main()