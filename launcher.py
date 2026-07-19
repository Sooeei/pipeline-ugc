"""Point d'entrée du .exe Windows : démarre le serveur local et ouvre la fenêtre de l'app.

Utilisé par PyInstaller (voir PipelineUGC.spec). En dev, on lance plutôt `python -m app.main`.
"""

from app.main import run

if __name__ == "__main__":
    run()
