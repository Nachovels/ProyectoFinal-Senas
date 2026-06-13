CREATE DATABASE IF NOT EXISTS speaking_hands;
USE accesclass;

CREATE TABLE roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(50) NOT NULL
);

INSERT INTO roles (nombre) VALUES ('admin'), ('coordinador'), ('estudiante');

CREATE TABLE usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    rol_id INT NOT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rol_id) REFERENCES roles(id)
);

-- Contraseña demo: "demo" (bcrypt)
INSERT INTO usuarios (nombre, email, password, rol_id) VALUES
('Admin Demo', 'admin@demo.cl', '$2b$12$kdMTHiUjz046/0SjGy6dcemtyOLAvPi.c7pcY.8Zd9jokPlcLvSei', 1),
('Coordinador Demo', 'coordinador@demo.cl', '$2b$12$kdMTHiUjz046/0SjGy6dcemtyOLAvPi.c7pcY.8Zd9jokPlcLvSei', 2),
('Estudiante Demo', 'estudiante@demo.cl', '$2b$12$kdMTHiUjz046/0SjGy6dcemtyOLAvPi.c7pcY.8Zd9jokPlcLvSei', 3);

CREATE TABLE sesiones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    coordinador_id INT NOT NULL,
    estudiante_id INT,
    codigo VARCHAR(6) UNIQUE NULL,
    iniciada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finalizada_en TIMESTAMP NULL,
    FOREIGN KEY (coordinador_id) REFERENCES usuarios(id),
    FOREIGN KEY (estudiante_id) REFERENCES usuarios(id)
);

CREATE TABLE participantes_sesion (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sesion_id INT NOT NULL,
    usuario_id INT NOT NULL,
    unido_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sesion_id) REFERENCES sesiones(id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
    UNIQUE KEY uq_sesion_usuario (sesion_id, usuario_id)
);

CREATE TABLE transcripciones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sesion_id INT NOT NULL,
    usuario_id INT NOT NULL,
    tipo ENUM('voz', 'frase_rapida', 'texto') NOT NULL,
    contenido TEXT NOT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sesion_id) REFERENCES sesiones(id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE frases_rapidas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    contenido VARCHAR(255) NOT NULL,
    dirigida_a ENUM('coordinador', 'estudiante') NOT NULL,
    categoria VARCHAR(100) NOT NULL DEFAULT 'General',
    activa TINYINT DEFAULT 1,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE senas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    imagen_url VARCHAR(255),
    video_url VARCHAR(255),
    categoria ENUM('abecedario', 'contexto_estudiantil', 'general') NOT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE registros_ia (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sesion_id INT NOT NULL,
    sena_detectada VARCHAR(100),
    confianza FLOAT,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
);

CREATE TABLE auditoria (
    id INT AUTO_INCREMENT PRIMARY KEY,
    actor_id INT NULL,
    accion VARCHAR(50) NOT NULL,
    detalle TEXT,
    sesion_id INT NULL,
    usuario_id INT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (actor_id) REFERENCES usuarios(id),
    FOREIGN KEY (sesion_id) REFERENCES sesiones(id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);