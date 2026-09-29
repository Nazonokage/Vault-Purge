from vault_purge.cli.main import app

if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    app()
