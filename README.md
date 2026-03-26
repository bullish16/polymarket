# 🤖 Polymarket BTC Up/Down 5-Min Bot

Bot trading otomatis untuk Polymarket BTC Up/Down 5-menit.

## Cara Kerja

1. Setiap 5 menit, Polymarket buka market: "BTC naik atau turun?"
2. Bot tunggu sampai **T-10 detik** sebelum window tutup
3. Cek arah BTC dari Binance (delta dari harga open window)
4. Kalau sinyal **kuat** (delta >0.05%), bet $1 sesuai arah
5. Tunggu resolusi, auto-claim kalau menang

## Strategi

- **Bet**: Max $1 per trade
- **Filter**: Hanya trade kalau delta >0.05% (win rate ~91% dari backtest)
- **Target**: Profit $0.30 per trade (jika entry di harga bagus)
- **Risk**: Max loss $1 per trade, max 3 loss berturut-turut (dari backtest 3 hari)

## Setup

### 1. Deploy ke VPS

```bash
# Upload files ke VPS
scp -r polymarket-bot/* root@YOUR_VPS:~/polymarket-bot/

# SSH ke VPS
ssh root@YOUR_VPS

# Run setup
cd ~/polymarket-bot
chmod +x deploy.sh start.sh stop.sh status.sh
./deploy.sh
```

### 2. Konfigurasi

Edit `.env`:
```
PRIVATE_KEY=your_key_here_without_0x
SIGNATURE_TYPE=1
```

Derive API credentials:
```bash
source venv/bin/activate
python3 setup_creds.py
# Copy output ke .env
```

### 3. Test dulu (Paper Trading)

```bash
./start.sh --dry
screen -r polybot   # Lihat output
```

### 4. Live Trading

```bash
./start.sh
```

## Commands

| Command | Fungsi |
|---|---|
| `./start.sh` | Start bot (live) |
| `./start.sh --dry` | Start bot (paper trade) |
| `./stop.sh` | Stop semua |
| `./status.sh` | Cek status |
| `screen -r polybot` | Lihat output bot |
| `screen -r polyclaim` | Lihat output claim |
| `tail -f bot.log` | Follow log |

## File

| File | Fungsi |
|---|---|
| `bot.py` | Main trading bot |
| `strategy.py` | Analisis sinyal (Binance → prediksi) |
| `auto_claim.py` | Auto-claim winning positions |
| `setup_creds.py` | Setup API credentials |
| `.env` | Config (JANGAN share!) |

## ⚠️ Risiko

- Bot ini **bukan jaminan profit**
- Win rate 84-91% dari backtest, tapi **past performance ≠ future results**
- Max bet $1 → max loss $1 per trade
- Butuh modal minimal $10-15 untuk survive losing streaks
- Selalu test dengan `--dry-run` dulu!
