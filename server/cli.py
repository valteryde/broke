
import sys
import os
from utils.models import User, create_user


def get_arg(index: int, default=None) -> str | None:
    try:
        return sys.argv[index]
    except IndexError:
        return default


def main():

    if get_arg(1) == 'create-user':
        username = get_arg(2)
        password = get_arg(3)
        email = get_arg(4)
        admin = get_arg(5, 0)

        if not username or not password or not email:
            print("Usage: cli.py create-user <username> <password> <email> <admin:0|1>")
            return
    
        if admin not in ['0', '1']:
            print("Admin flag must be 0 or 1")
            return
        admin = int(admin)

        user = create_user(username, password, email=email, admin=admin)
        print(f"User '{user.username}' created.")


if __name__ == '__main__':
    main()
