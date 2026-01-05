# **Avris Blockchain Documentation**  

## **📌 Overview**  
Avris is a **Proof-of-Work (PoW) blockchain** with dynamic transaction fees, miner difficulty adjustments, and a unique **AvriGuard** mechanism to prevent mining centralization . This document explains all network endpoints, economic rules, and security features in detail. This is still under heavy development!

---

## **🔗 Core Features**  

### **1. Dynamic Transaction Fees**  
- **Fee Range** 0.1% (min) to 1% (max) of transaction value 

- **Adjustment Mechanism**
  - Fee scales **linearly** with mempool congestion  
  - Formula:  
    ```  
    fee = min(base_fee + (mempool_fullness × (max_fee - base_fee)), max_fee)  
    ```  
  - Rounded to nearest **0.1%** increment for cleaner UX  

- **Mempool Impact**
  - Higher fees incentivize miners to prioritize transactions during congestion.
  - Lower fees when mempool is empty (1% floor)
- **Miners are encouraged to keep mining and secure the network.**

### **2. Hashing Algorithm (Grøstl)**  

- Used for
  - **Block hashing** (`calculate_hash` in `Block` class)  
  - **Transaction IDs** (`calculate_txid`) 

- Benefits
  - Faster than SHA-3 while maintaining security  
  - Resistant to ASIC mining (helps decentralization)  

### **3. Difficulty Adjustment**  
- **Target Block Time**: **5 minutes**  
- **Adjusts Every**: **12 blocks (~1 hour)**  
- **Formula**:  
  - If blocks are too fast → **Increase difficulty**  
  - If blocks are too slow → **Decrease difficulty**  

---

## **📡 Network & API Endpoints**  

### **🔹 Blockchain Info**  
| Endpoint | Description |  
|----------|-------------|  
| `GET /network/info` | Chain height, difficulty, supply |  
| `GET /network/chain` | Full blockchain data |  
| `GET /network/latestblock` | Latest block details |  
| `GET /network/hashrate` | Estimated network hashrate |  
| `GET /network/block/<txid/num>/summary`| Get the summary of a block |
| `GET /network/block/<txid/num>/transactions`| Get the transactions of a block |


### **🔹 Transactions & Fees**  
| Endpoint | Description |  
|----------|-------------|  
| `POST /transaction/create` | Submit a new transaction |  
| `GET /network/fee_estimate` | Current fee rate & mempool status |  
| `GET /network/fee_chart` | Fee structure visualization |  

### **🔹 Mining**  
| Endpoint | Description |  
|----------|-------------|  
| `GET /mining/info` | Current difficulty & latest block |  
| `POST /mining/submitblock` | Submit a mined block |  

### **🔹 Wallet & Addresses**  
| Endpoint | Description |  
|----------|-------------|  
| `GET /wallet/create` | Generate a new wallet (address + seed) |  
| `POST /wallet/import` | Import wallet using seed |  
| `GET /wallet/validate/<addr>` | Check if address is valid |  
| `GET /user/balance/<addr>` | Get balance for an address |  

### **🔹 Avris Guard**  
| Endpoint | Description |  
|----------|-------------|  
| `GET /network/checkaddrdiff/<addr>` | Check if miner is under high difficulty |  

---

## **⚙️ Technical Details**  

### **📌 Address Generation**  
- **Format**: `AVRI-[4 words]-[checksum]` (e.g., `AVRI-sunset-cat-moon-tree-1a3f`)  
- **Derived from**:  
  - BIP-39 wordlist (`words.txt`)  
  - SHA-256 hashing of seed  
- **Checksum**: First 4 chars of `SHA256(phrase)`  

### **📌 Mempool Mechanics**  
- **Max Size**: **10,000 transactions**  
- **Block Limit**: **512 transactions/block**  
- **Prioritization**: Sorts by **highest fee**  

---

## **🔒 Security Notes**  
- **Avris Guard** prevents 51% attacks by penalizing fast miners.  
- **Dynamic fees** reduce spam transactions.  
- **Seed phrases** must be kept secure (wallet recovery depends on them).  

## **🔐 Security & Anti-Centralization**  


### **Avris Guard Mechanism**  

- **Purpose**: Prevent mining monopolies. 

- **How It Works**:  

  1. Tracks **each miner’s block rate**.  
  2. If a miner exceeds **10 blocks/hour**, their **difficulty increases by 50% per extra block**.  
  3. Returns to normal if activity slows.  

- **Endpoint**:  
  - `GET /network/checkaddrdiff/<address>` → Check if a miner is penalized.  

📌 **Example**:  
- Miner A submits **15 blocks/hour** → **Difficulty × 2.5** (slowing them down).  

---

## **💰 Tokenomics (AVRI Coin)**  

| **Parameter** | **Value** | **Description** |  
|--------------|----------|----------------|  
| **Block Reward** | 80 AVRI | New coins per block |  
| **Transaction Fee** | 1%–5% | Dynamic, scales with demand |  
| **Max Supply** | 67,200,000 | Adjustable via governance |
| **Block Halving** | Halves every 420,000 blocks | Halving events occur roughly every 4 years |

## Block Halving Events
| **Era** | **Block Range** | **Reward per Block** | **Total Coins from Era**|
|------------------|----------|-------------------|-----------------------|   
| 1 | 0 to 419,999 | 80 | ~33,600,000 |
| 2 | 420,000 to 839,999 | 40 | ~16,800,000 |
| 3 | 840,000 to 1,259,999 | 20 | ~8,400,000 |
| 4 | 1,260,000 to 1,679,999 | 10 | ~4,200,000 |
| 5 | 1,680,000 to 2,099,999 | 5 | ~2,100,000 |


## **Avris Unique Dual Chain system**
- Avris implements a dual-layer mining system where two types of devices mine different layers of the same blockchain:
- In order to remain decentralised whilst still allowing low power arduinos to mine we have come up with this solution
---

### Main Chain (PC/GPU Miners)

| Feature | Description |
|--------|-------------|
| **Algorithm** | Grøstl Proof-of-Work |
| **Block Target** | 5 minutes |
| **Block Rewards** | 80 AVR → halves every 420,000 blocks |
| **Role** | Secures the entire network |
| **Relation to Mini-Chain** | Embeds Mini-Chain Merkle Root |

### MiniAVR chain (Arduino/ESP Miners)

| Feature | Description |
|--------|-------------|
| **Algorithm** | SHA-1 Proof-of-Work |
| **Block Target** | ~30 seconds |
| **Reward** | Fixed 1 AVR per mini-block |


📌 **Key Insight**:  
- PC Miners earn **80 AVRI** per block(Plus any address to address transaction fees).  
- Fees **do not burn**—they go to the **miner that sucessfully solved the block** 

---

## **📜 License**  
GNU General Public License v3.0  

---

### **🎯 Summary**  
✅ **Dynamic fees** prevent congestion exploitation  
✅ **Avris Guard** keeps mining decentralized  
✅ **Grøstl** ensures fast & asic resistant hashing  
✅ **Partial Web3 RPC** currently implementing support for compatibility  

For more details, check the [OpenAPI spec](#) (if implemented).
Check out the [Discord](https://discord.gg/zYdeBw7gwB)

🚀 **Happy mining!** 🚀