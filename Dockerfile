# Use full Python build, not slim
FROM python:3.13

# Set working directory inside the container
WORKDIR /app

# Copy your project files into the container
COPY . .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Command to run your bot
CMD ["python", "tm/main.py"]
