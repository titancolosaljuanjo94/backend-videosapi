# Utiliza una imagen oficial de Python como base
FROM python:3.10-slim

# Instala ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos de dependencias
COPY requirements.txt ./

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código fuente
COPY . .

# Expone el puerto que Cloud Run inyecta vía $PORT
EXPOSE 8080

# Arranca el servidor FastAPI; Cloud Run define $PORT (por defecto 8080)
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]
