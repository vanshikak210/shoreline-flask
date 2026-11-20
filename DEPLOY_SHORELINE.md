# Deploying Shoreline on the OCS server (Cockpit)

Shoreline's ports: **8550** = Flask API, **8551** = socket server.
Local dev is unchanged (`python main.py` still runs on 8587).

## 1. Clone (Cockpit → Terminal)
```bash
cd ~
git clone https://github.com/vanshikak210/shoreline-flask.git
cd shoreline-flask
```

## 2. Database settings (.env)
```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # copy this for SECRET_KEY
vim .env        # or: nano .env
```
Fill in SECRET_KEY, ADMIN_PASSWORD, DEFAULT_PASSWORD, and put your frontend
domain in EXTRA_CORS_ORIGINS (e.g. `https://shoreline-api.opencodingsociety.com`).
vim: press `i` to type, `Esc` then `:wq` + Enter to save.

## 3. Build and run with Docker
```bash
docker-compose up -d --build
docker ps                                  # shoreline_flask should be "Up"
curl -s localhost:8550/api/id             # {"message": ...} = Flask is answering
```

## 4. Set up the database (first deploy only)
```bash
docker-compose exec web python scripts/db_init.py
```
Warning: db_init **wipes** the tables. Run it once; never again after real users sign up.

## 5. nginx + HTTPS
```bash
sed -i 's/shoreline-api.opencodingsociety.com/shoreline-api.opencodingsociety.com/' nginx_shoreline.conf   # your backend domain
sudo cp nginx_shoreline.conf /etc/nginx/sites-available/shoreline
sudo ln -s /etc/nginx/sites-available/shoreline /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d shoreline-api.opencodingsociety.com
```

## Updating later
```bash
cd ~/shoreline-flask && git pull && docker-compose up -d --build
```
Logs: `docker-compose logs -f web`
