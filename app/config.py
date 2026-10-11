from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False)
    bot_token: SecretStr = Field(validation_alias='BOT_TOKEN')
    owner_id: int = Field(validation_alias='OWNER_ID', gt=0)
    mongodb_uri: SecretStr = Field(validation_alias='MONGODB_URI')
    mongodb_db_name: str = Field(default='file_bot', validation_alias='MONGODB_DB_NAME')

