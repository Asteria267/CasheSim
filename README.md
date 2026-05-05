
# 🧠 CPU Cache Hierarchy Simulator

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![CLI](https://img.shields.io/badge/interface-CLI%20%2B%20Interactive-orange)
![Visualization](https://img.shields.io/badge/visualization-rich-purple)

A visually rich **CPU cache simulator** that models a **2-level cache hierarchy (L1 + L2)** with **LRU eviction**, cycle cost estimation, and real-time terminal animation.

Designed for **learning**, **teaching**, and **performance intuition**, especially for embedded systems and Cortex-M–style memory behavior.

---

## ✨ Features

- 🧠 **Two-level cache simulation** (L1 + L2)
- 🔁 **LRU (Least Recently Used)** eviction policy
- ⚡ **Cycle-accurate cost model**
  - L1 hit: 2 cycles  
  - L2 hit: 10 cycles  
  - Miss: 100 cycles
- 📊 **Live terminal animation** using `rich`
- 📈 **Detailed statistics**
  - Hit/miss rates
  - Average cycles
  - Total penalty vs ideal
- 🔬 **NumPy-powered analysis summary**
- 🎯 **Preset workloads** + custom sequences
- 🧩 Clean, modular architecture

---

## 📦 Installation

```bash
git clone https://github.com/yourusername/cache-simulator.git
cd cache-simulator
pip install -r requirements.txt
````

Or install manually:

```bash
pip install rich numpy
```

---

## 🚀 Usage

### Interactive Mode

```bash
python cache_sim.py
```

Launches a guided interface to:

* Choose workload presets
* Customize cache sizes
* Control animation speed

---

### Run a Preset

```bash
python cache_sim.py --preset thrash
```

---

### Custom Access Pattern

```bash
python cache_sim.py --seq "0 1 2 3 0 1 4"
```

---

### Customize Cache Sizes

```bash
python cache_sim.py --l1 8 --l2 16 --preset sequential
```

---

### Disable Animation (fast mode)

```bash
python cache_sim.py --no-animate --preset mixed
```

---

### List Available Presets

```bash
python cache_sim.py --list-presets
```

---

## 🧪 Workload Presets

| Preset        | Description                            |
| ------------- | -------------------------------------- |
| `temporal`    | Repeated access → strong locality      |
| `sequential`  | Linear scan → spatial locality         |
| `thrash`      | Cache-sized stride → constant eviction |
| `mixed`       | Realistic firmware-like pattern        |
| `hot_data`    | One dominant address                   |
| `stride2`     | Moderate locality (step=2)             |
| `working_set` | Growing memory pressure                |

---

## 📊 Example Output

* Live cache state visualization
* Access grid with color-coded results:

  * 🟩 L1 hit
  * 🟧 L2 hit
  * 🟥 Miss
  * 🟨 Eviction
* Detailed logs of:

  * Each memory access
  * Evictions (L1/L2)
  * Cycle cost

---

## 🧠 How It Works

### Cache Model

* **L1 Cache**

  * Small, fast
  * Checked first

* **L2 Cache**

  * Larger, slower
  * Acts as fallback

* **Main Memory**

  * Accessed on miss

---

### Access Flow

```
Access → L1?
        ├── Hit → Done (2 cycles)
        └── Miss → L2?
                  ├── Hit → Promote to L1 (10 cycles)
                  └── Miss → Load to L2 + L1 (100 cycles)
```

---

### Replacement Policy

* **LRU (Least Recently Used)**
* Implemented via `OrderedDict`
* Evicts the oldest unused entry when full

---

## 📈 Metrics Tracked

* L1 hit rate
* L2 hit rate
* Miss rate
* Total cycles
* Average cycles per access
* Cycle penalty vs ideal L1-only execution

---

## 🔬 NumPy Analysis

At the end of each run:

* Address distribution
* Unique addresses
* Cycle statistics (min/max/mean/std)
* Access pattern breakdown

---

## 🛠️ Architecture

```
cache_sim.py
│
├── CacheSimulator   # Core simulation engine
├── LRUCache         # LRU implementation
├── AccessResult     # Per-access record
├── SimStats         # Aggregated statistics
│
├── Rendering Layer (rich)
│   ├── Live animation
│   ├── Cache tables
│   ├── Stats dashboard
│   └── Access log
│
└── CLI + Interactive Menu
```

---

## 🎯 Use Cases

* 📚 Teaching cache behavior
* 🧑‍💻 Understanding performance bottlenecks
* ⚙️ Embedded systems intuition
* 🧪 Experimenting with access patterns
* 🧵 Visual debugging of memory locality

---

## 🔮 Future Improvements

* [ ] Configurable associativity (set-associative caches)
* [ ] Write-through / write-back policies
* [ ] Real trace import (e.g., MCU DWT logs)
* [ ] GUI version (web or desktop)
* [ ] Multi-core simulation

---

## 🤝 Contributing

Pull requests are welcome. If you want to improve performance modeling, visualization, or add new cache policies — go for it.

---

## 📄 License

MIT License — feel free to use, modify, and distribute.

---

## ⭐ Final Note

This project is built to make cache behavior **visible and intuitive** — something that’s usually hidden deep inside hardware.

If you’ve ever struggled to *feel* why caches matter, this should help.

```

---
