FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt /app/

# install git first (για να μπορεί να κατεβάσει mydatanaut)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# upgrade pip και dependencies (περιλαμβάνει gunicorn)
RUN pip install --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# φτιάχνουμε φακέλους για uploads & data
RUN mkdir -p /app/uploads /app/data \
  && chown -R root:root /app/uploads /app/data /app

# εκκίνηση gunicorn στο port 10000
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
