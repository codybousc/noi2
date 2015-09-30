from flask import Flask
from flask.ext.testing import TestCase
from nose.tools import eq_
from sqlalchemy.exc import OperationalError, IntegrityError
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import psycopg2

from .util import load_fixture
from .. import models

db = models.db

PG_USER = 'postgres'
PG_HOST = 'db'
PG_DBNAME = 'noi_test'

# We can't use postgres on Travis CI builds until
# https://github.com/GovLab/noi2/issues/23 is fixed.
USE_POSTGRES = False

if USE_POSTGRES:
    TEST_DB_URL = 'postgres://%s:@%s:5432/%s' % (PG_USER, PG_HOST, PG_DBNAME)
else:
    TEST_DB_URL = 'sqlite://'

def create_postgres_database():
    con = psycopg2.connect(user=PG_USER, host=PG_HOST, dbname='postgres')
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    cur.execute('CREATE DATABASE ' + PG_DBNAME)
    cur.close()
    con.close()

class DbTestCase(TestCase):
    BASE_APP_CONFIG = dict(
        SQLALCHEMY_DATABASE_URI=TEST_DB_URL,
        NOI_DEPLOY='_default',
        SEARCH_DEPLOYMENTS=['_default']
    )

    def create_app(self):
        app = Flask('test')
        app.config.update(self.BASE_APP_CONFIG)
        db.init_app(app)
        return app

    def setUp(self):
        try:
            db.create_all()
        except OperationalError, e:
            db_noexist_msg = 'database "%s" does not exist' % PG_DBNAME
            if USE_POSTGRES and db_noexist_msg in str(e):
                create_postgres_database()
                db.create_all()
            else:
                raise e

    def tearDown(self):
        db.session.remove()
        db.drop_all()

class UserDbTests(DbTestCase):
    def test_ensure_deployment_has_a_default_setting(self):
        u = models.User(email=u'a@example.org', password='a', active=True)
        db.session.add(u)
        db.session.commit()
        eq_(u.deployment, '_default')

    def test_ensure_user_is_constrained_by_deployment_and_email(self):
        a1 = models.User(email=u'a@example.org', password='a', active=True,
                         deployment='1')
        a2 = models.User(email=u'a@example.org', password='a', active=True,
                         deployment='2')
        db.session.add(a1)
        db.session.add(a2)
        db.session.commit()

        with self.assertRaises(IntegrityError):
            a1 = models.User(email=u'a@example.org', password='u',
                             active=True, deployment='1')
            db.session.add(a1)
            db.session.commit()

class UserSkillDbTests(DbTestCase):
    def setUp(self):
        super(UserSkillDbTests, self).setUp()
        load_fixture()
        self.sly_less = models.User.query_in_deployment()\
          .filter(models.User.email=='sly@stone-less-knowledgeable.com')\
          .one()

    def test_get_most_complete_profiles_works(self):
        users = models.User.get_most_complete_profiles()
        self.assertEqual(users[-1].email, 'sly@stone-less-knowledgeable.com')

    def test_questionnaire_progress_works(self):
        progress = self.sly_less.questionnaire_progress
        self.assertEqual(progress['opendata']['answered'], 4)
        self.assertEqual(progress['prizes']['answered'], 0)

    def test_skill_levels_works(self):
        self.assertEqual(self.sly_less.skill_levels, {
            u'opendata-implementing-an-open-data-program-data-quality-and-integrity': -1,
            u'opendata-implementing-an-open-data-program-frequency-of-release': -1,
            u'opendata-implementing-an-open-data-program-managing-open-data': -1,
            u'opendata-implementing-an-open-data-program-open-data-standards': -1
        })

class UserRegistrationTests(DbTestCase):
    def setUp(self):
        super(UserRegistrationTests, self).setUp()
        user = models.User(email=u'a@example.org', password='a', active=True)
        db.session.add(user)
        db.session.commit()
        self.user = user

    def test_user_is_not_fully_registered_by_default(self):
        eq_(self.user.has_fully_registered, False)

    def test_set_fully_registered_works(self):
        self.user.set_fully_registered()
        eq_(self.user.has_fully_registered, True)

    def test_multiple_join_events_are_not_created(self):
        self.user.set_fully_registered()
        self.user.set_fully_registered()
        join_events = db.session.query(models.SimpleUserEvent).\
                      filter(models.SimpleUserEvent.user_id==self.user.id).\
                      filter(models.SimpleUserEvent.subtype==\
                             models.SimpleUserEvent.SUBTYPE_USER_JOINED).\
                      all()
        eq_(len(join_events), 1)

class SharedMessageDbTests(DbTestCase):
    def test_only_events_in_deployments_are_seen(self):
        other = models.User(email=u'b@example.org', password='a', active=True,
                            deployment='other')
        a = models.User(email=u'a@example.org', password='a', active=True,
                        deployment='_default')
        db.session.add(other)
        db.session.add(a)
        db.session.commit()
        message1 = models.SharedMessageEvent.from_user(a, message="hi")
        message2 = models.SharedMessageEvent.from_user(other, message="other")
        db.session.add(message1)
        db.session.add(message2)
        db.session.commit()
        messages = models.Event.query_in_deployment()
        eq_(messages.count(), 1)
        eq_(messages[0].type, 'shared_message')
        eq_(messages[0].message, 'hi')
        eq_(messages[0].user.email, 'a@example.org')

def test_users_only_display_in_search_if_they_have_first_and_last_name():
    user = models.User()
    eq_(user.display_in_search, False)
    user.first_name = "John"
    eq_(user.display_in_search, False)
    user.last_name = "Doe"
    eq_(user.display_in_search, True)
