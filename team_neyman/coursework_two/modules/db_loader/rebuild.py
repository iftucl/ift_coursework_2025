from modules.db_loader import minio_db, mongodb

if __name__ == "__main__":
    minio_db.reset_minio()
    mongodb.reset_mongodb()
