# ⚾ AI Baseball Matchup Analyzer

An AI-powered baseball matchup analysis tool built with **IBM watsonx.ai**, the **MLB Stats API**, and **The Odds API**.

Select any game from today's MLB schedule and get an instant AI-generated scouting report that incorporates real-time betting odds, probable pitchers, and team context.

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Engine | IBM watsonx.ai (Granite LLM) |
| Backend | Python / Flask |
| Baseball Data | MLB Stats API (free, no key needed) |
| Betting Odds | The Odds API (free tier) |
| Hosting | IBM Code Engine |

---

## 🚀 Local Setup

### 1. Clone the repo
```bash
git clone https://github.com/yourusername/baseball-analyzer.git
cd baseball-analyzer
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set up environment variables
```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

**Getting your keys:**
- **IBM_API_KEY**: [IBM Cloud IAM](https://iam.cloud.ibm.com/) → API Keys → Create
- **IBM_PROJECT_ID**: [watsonx.ai](https://dataplatform.cloud.ibm.com/) → Your Project → Settings
- **ODDS_API_KEY**: [the-odds-api.com](https://the-odds-api.com/) → Sign up for free

### 4. Run the app
```bash
flask run
```
Visit `http://localhost:5000`

---

## ☁️ Deploy to IBM Code Engine (Free)

1. Push your code to GitHub (make sure `.env` is in `.gitignore`)
2. Go to [IBM Cloud Code Engine](https://cloud.ibm.com/codeengine)
3. Create a new **Application** → point to your GitHub repo
4. Set environment variables in the Code Engine dashboard (your API keys)
5. Deploy — Code Engine gives you a public URL

---

## 📁 Project Structure

```
baseball-analyzer/
├── app.py              # Flask backend + API integrations
├── templates/
│   └── index.html      # Frontend UI
├── requirements.txt
├── Procfile            # For deployment
├── .env.example        # Environment variable template
└── .gitignore
```

---

## ⚠️ Disclaimer

This tool is for educational and entertainment purposes only. AI analysis does not constitute financial or betting advice.