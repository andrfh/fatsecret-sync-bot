from repositories.user_repository import create_user, get_user
from models.User import User

from database.init_db import init_db

#test data
test_user = User(
    telegram_id = 1123412342345,
    language = None,
    fatsecret_token = None,
    fatsecret_token_secret = None,
    fatsecret_connected_at = None
)

#test init
print("DATABASE INIT TEST:")
try:
    init_db()
    print("Database succesfull initialited")
except Exception as error:
    print(f"Database initialization failed \n Error:{error}")


#test create user
print("\nCREATE USER TEST:")
try:
    create_user(test_user.telegram_id)
    print("User created succesfull")
except Exception as error:
    print(f"User create failed \n Error:{error}")

#test duble create user
print("\nDOUBLE-CREATE USER TEST:")
try:
    create_user(test_user.telegram_id)
    print("User double-created succesfull")
except Exception as error:
    print(f"User double-create failed \n Error:{error}")


#test get user
print("\nGET USER TEST:")
try:
    user = get_user(test_user.telegram_id)
    if user is not None:
        print(f"User: {user}")
    else:
        print("User not found")
except Exception as error:
    print(f"User search failed \n Error:{error}")

#test get not existed user
print("\nGET NOT EXISTENT USER TEST:")
try:
    user = get_user(0)
    if user != None:
        print(f"Not existing user foun: {user}")
    elif user == None:
        print("Not existing user not found")
except Exception as error:
    print(f"User search failed \n Error:{error}")

