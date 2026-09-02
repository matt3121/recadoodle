"""Local-only account administration; no public admin website or default password."""
import argparse
from getpass import getpass

from werkzeug.security import generate_password_hash

from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account, PlatformAccountLink
from rrserver.security import password_problem


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['create-developer', 'link-platform'])
    parser.add_argument('--username')
    parser.add_argument('--account-id', type=int)
    parser.add_argument('--platform', choices=['0', '1', '2', '3', '4', '5'])
    parser.add_argument('--platform-id')
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        if args.command == 'create-developer':
            if not args.username or not 1 <= len(args.username) <= 32:
                parser.error('--username must be 1–32 characters')
            if db.session.scalar(db.select(Account).where(db.func.lower(Account.username) == args.username.lower())):
                parser.error('username already exists; no account changed')
            password = getpass('Password (12+ characters): ')
            problem = password_problem(password)
            if problem:
                parser.error(problem)
            if getpass('Confirm password: ') != password:
                parser.error('passwords do not match')
            account = Account(username=args.username, display_name=args.username,
                              password_hash=generate_password_hash(password),
                              is_developer=True, is_moderator=True,
                              token_balance=app.config['STARTING_TOKENS'])
            db.session.add(account)
            db.session.commit()
            print(f'Created developer account {account.id}: {account.username}')
        else:
            if not args.account_id or args.account_id == 1 or not args.platform or not args.platform_id:
                parser.error('supply --account-id (not Coach), --platform and --platform-id')
            if len(args.platform_id) > 128:
                parser.error('platform ID too long')
            account = db.session.get(Account, args.account_id)
            if account is None or not account.password_hash:
                parser.error('account must exist and have a password')
            db.session.merge(PlatformAccountLink(platform=args.platform, platform_id=args.platform_id,
                                                account_id=account.id))
            db.session.commit()
            print('Account picker linked. Password authentication is still required.')


if __name__ == '__main__':
    main()
