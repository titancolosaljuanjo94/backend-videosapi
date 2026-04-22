# Utiliza una imagen oficial de Python como base
FROM python:3.10-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos de dependencias
COPY requirements.txt ./

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código fuente
COPY . .

# Expone el puerto (ajusta si usas otro)
EXPOSE 8000

# Comando por defecto para ejecutar la app (ajusta si usas otro archivo)
CMD ["python", "main.py"]
