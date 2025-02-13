# Use an official Python runtime as a parent image
FROM python:3.10

# Set the working directory
WORKDIR /app

# Copy the project files into the container
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (change as needed)
EXPOSE 8000

# Command to run the app (modify based on your application)
CMD ["python", "app.py"]
