black --check tom/*.py test/*.py
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
python3 -m pytest --show-capture=all -vv
