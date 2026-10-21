#!/bin/bash
set -e
cd /var/www/yahya_bhai/PL_Acquistion
git pull origin main
env/bin/python -m pip install -r requirements.txt -q
env/bin/python manage.py migrate --noinput
env/bin/python manage.py collectstatic --noinput
sudo systemctl restart gunicorn.service
echo "Deployed $(git rev-parse --short HEAD)"
