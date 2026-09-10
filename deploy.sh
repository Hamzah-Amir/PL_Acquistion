#!/bin/bash
set -e
cd /var/www/yahya_bhai/PL_Acquistion
git pull origin main
source env/bin/activate
pip install -r requirements.txt -q
python manage.py migrate --noinput
python manage.py collectstatic --noinput
deactivate
sudo systemctl restart gunicorn.service
echo "Deployed $(git rev-parse --short HEAD)"
