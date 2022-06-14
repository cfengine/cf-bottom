echo "Check formatting with black"
python -m pip install --upgrade pip
python -m pip install black
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
black --check tom/*.py test/*.py

echo "Lint with flake8"
# stop the build if there are Python syntax errors or undefined names
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
# exit-zero treats all errors as warnings. The GitHub editor is 127 chars wide
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics

echo "test with pytest"
python -m pytest # use this form instead of pytest executable to get local path in python sys.path
