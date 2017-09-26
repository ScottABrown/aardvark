'''Test cases for the manage.config() function.

We test the following for the configurable parameters:
- Exactly the expected parameters appear in the config file.
- The expected parameters have the expected values in the config file.


Set the SWAG_CONFIG_TEST_ARCHIVE_DIR environment variable to the
absolute path to the directory to use to archive test artifacts in the
case of test failures. The default is '/tmp'.

At the start of each test case, set self.archive_case_artifacts_as to
a distinct string to use to name the archive files created if that
test case fails. The recommended value is the name of the test
function.

As the last line of each case set self.archive_case_artifacts_as to
None.

If the value of self.archive_case_artifacts_as is not None in
tearDown, the config file, the command line call to "aardvark config"
and a transcript of the command line interaction will be archived in
the archive directory in "command.*" and "config.py.*", where the
wildcard is replaced by the value of self.archive_case_artifacts_as.


Set the SWAG_CONFIG_TEST_COMMAND_ARCHIVE_DIR environment variable to
the absolute path to the directory to use to archive the commands
issued in test cases.  The default is to use the same value as
SWAG_CONFIG_TEST_ARCHIVE_DIR. This will create a record of all the
command lines executed in execution of these test cases, in files
names "commands.[TestClassName]".


Some of the test cases provided check for proper behavior when the
phantomjs executable can be located by
distutils.spawn.find_executable() and some check proper behavior when
the executable can't be located. Tests with such a dependency will be
skipped if the dependency isn't satisfied. Manually rename or move
the phantomjs executable to enable tests that require it not be
found.

'''

# Note: regarding keeping the archive_test_case_artifacts_as in sync
# with test case names, check the output of this command:
# egrep "def test_|artifacts_as =" test_config.py |\
# sed -E "s/(.*(def |= '|self.*None)|\(self\):)|'//g"

import os
import shutil
import tempfile

import unittest
from distutils.spawn import find_executable

from aardvark import manage
import pexpect

# These are fast command line script interactions, eight seconds is forever.
EXPECT_TIMEOUT = 8

CONFIG_FILENAME = 'config.py'
PHANTOMJS_EXECUTABLE = find_executable(manage.PHANTOMJS_EXECUTABLE)

# Locations where we will archive test artifacts.
DEFAULT_ARTIFACT_ARCHIVE_DIR = '/tmp'
ARTIFACT_ARCHIVE_DIR = (
    os.environ.get('SWAG_CONFIG_TEST_ARCHIVE_DIR') or
    DEFAULT_ARTIFACT_ARCHIVE_DIR
    )
COMMAND_ARCHIVE_DIR = (
    os.environ.get('SWAG_CONFIG_TEST_COMMAND_ARCHIVE_DIR') or
    ARTIFACT_ARCHIVE_DIR
    )

DEFAULT_LOCALDB_FILENAME = 'aardvark.db'
DEFAULT_AARDVARK_ROLE = 'Aardvark'
DEFAULT_NUM_THREADS = 5

# Specification of option names, default values, methods of extracting
# from config file, etc. The keys here are what we use as the 'handle'
# for each configurable option throughout this test file.
CONFIG_OPTIONS = {
    'swag_bucket': {
        'short': '-b',
        'long': '--swag-bucket',
        'config_key': 'SWAG_OPTS',
        'config_prompt': r'(?i).*SWAG.*BUCKET.*:',
        'getval': lambda x: x.get('swag.bucket_name') if x else None,
        'default': manage.DEFAULT_SWAG_BUCKET
        },
    'aardvark_role': {
        'short': '-a',
        'long': '--aardvark-role',
        'config_key': 'ROLENAME',
        'config_prompt': r'(?i).*ROLE.*NAME.*:',
        'getval': lambda x: x,
        'default': manage.DEFAULT_AARDVARK_ROLE
        },
    'phantom': {
        'short': None,
        'long': '--phantom',
        'config_key': 'PHANTOMJS',
        'config_prompt': r'(?i).*phantomjs.*:',
        'getval': lambda x: x,
        'default': PHANTOMJS_EXECUTABLE
        },
    'db_uri': {
        'short': '-d',
        'long': '--db-uri',
        'config_key': 'SQLALCHEMY_DATABASE_URI',
        'getval': lambda x: x,
        'config_prompt': r'(?i).*DATABASE.*URI.*:',
        'default': None  # need to be in tmpdir.
        },
    'num_threads': {
        'short': None,
        'long': '--num-threads',
        'config_key': 'NUM_THREADS',
        'config_prompt': r'(?i).*THREADS.*:',
        'getval': lambda x: x,
        'default': manage.DEFAULT_NUM_THREADS
        },
    }

# Syntax sugar for getting default parameters for each option. Note
# that we reset the db_uri value after we change the working directory
# in setUpClass().
DEFAULT_PARAMETERS = dict([
    (k, v['default']) for k, v in CONFIG_OPTIONS.items()
    ])
DEFAULT_PARAMETERS_NO_SWAG = dict(DEFAULT_PARAMETERS, **{'swag_bucket': None})

# Message strings for skipIf.
INSTALL_PHANTOM = (
    "The phantomjs executable must be locatable by find_executable()",
    " to run tests that depend on finding it."
    )
HIDE_PHANTOM = (
    "Manually remove or temporarily rename the phantomjs executable",
    " to run no-phantom cases."
    )

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# Uncomment to show lower level logging statements.
# import logging
# logger = logging.getLogger()
# logger.setLevel(logging.DEBUG)
# shandler = logging.StreamHandler()
# shandler.setLevel(logging.INFO)  # Pick one.
# <!-- # shandler.setLevel(logging.DEBUG)  # Pick one. -->
# formatter = logging.Formatter(
#     '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
# shandler.setFormatter(formatter)
# logger.addHandler(shandler)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def default_db_uri():
    '''Return the default db_uri value at runtime.'''
    return '{localdb}:///{path}/{filename}'.format(
        localdb=manage.LOCALDB,
        path=os.getcwd(),
        filename=manage.DEFAULT_LOCALDB_FILENAME
        )


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def get_config_option_string(cmdline_option_spec, short_flags=True):
    '''Construct the options string for a call to aardvark config.'''

    option_substrings = []

    for param, value in cmdline_option_spec.items():
        flag = (
            CONFIG_OPTIONS[param]['short']
            if short_flags and CONFIG_OPTIONS[param]['short']
            else CONFIG_OPTIONS[param]['long']
            )
        option_substrings.append('{} {}'.format(flag, value))

    return ' '.join(option_substrings)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def load_configfile(cmdline_option_spec):
    '''Evaluate the config values for the fields in cmdline_option_spec.'''

    all_config = {}
    execfile(CONFIG_FILENAME, all_config)
    # print all_config.keys()
    found_config = dict([
        (k, v['getval'](all_config.get(v['config_key'])))
        for (k, v) in CONFIG_OPTIONS.items()
        ])
    return found_config


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def get_expected_config(option_spec):
    '''Return a dict with the values that should be set by a config file.'''

    include_swag = ('swag_bucket' in option_spec)
    default_parameters = (
        DEFAULT_PARAMETERS if include_swag else DEFAULT_PARAMETERS_NO_SWAG
        )
    expected_config = dict(default_parameters)
    expected_config.update(option_spec)

    return expected_config


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TestConfigBase(unittest.TestCase):
    '''Base class for config test cases.'''

    # Throughout, the dicts cmdline_option_spec and config_option_spec
    # are defined with keys matching the keys in CONFIG_SPEC and the
    # values defining the value for the corresponding parameter, to be
    # delivered via a command line parameter to 'aardvark config' or
    # via entry after the appropriate prompt interactively.

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @classmethod
    def setUpClass(cls):
        '''Test case class common fixture setup.'''

        cls.tmpdir = tempfile.mkdtemp()
        cls.original_working_dir = os.getcwd()
        os.chdir(cls.tmpdir)

        cls.commands_issued = []

        # These depend on the current working directory set above.
        CONFIG_OPTIONS['db_uri']['default'] = default_db_uri()
        DEFAULT_PARAMETERS['db_uri'] = CONFIG_OPTIONS['db_uri']['default']
        DEFAULT_PARAMETERS_NO_SWAG['db_uri'] = (
            CONFIG_OPTIONS['db_uri']['default']
            )

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @classmethod
    def tearDownClass(cls):
        '''Test case class common fixture teardown.'''

        os.chdir(cls.original_working_dir)
        cls.clean_tmpdir()
        os.rmdir(cls.tmpdir)

        command_archive_filename = '.'.join(['commands', cls.__name__])
        command_archive_path = os.path.join(
            COMMAND_ARCHIVE_DIR, command_archive_filename
            )

        with open(command_archive_path, 'w') as fptr:
            fptr.write('\n'.join(cls.commands_issued) + '\n')

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @classmethod
    def clean_tmpdir(cls):
        '''Remove all content from cls.tmpdir.'''
        for root, dirs, files in os.walk(cls.tmpdir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def setUp(self):
        '''Test case common fixture setup.'''
        self.clean_tmpdir()
        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.last_transcript = []

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def tearDown(self):
        '''Test case common fixture teardown.'''

        # Archive the last command and config file created, if indicated.
        if self.archive_case_artifacts_as:

            command_archive_path = self.archive_path(
                'command', self.archive_case_artifacts_as
                )
            config_archive_path = self.archive_path(
                CONFIG_FILENAME, self.archive_case_artifacts_as
                )

            with open(command_archive_path, 'w') as fptr:
                fptr.write(self.last_config_command + '\n')
                if self.last_transcript:
                    fptr.write(
                        '\n'.join(
                            map(lambda x: str(x), self.last_transcript)
                            ) + '\n'
                        )

            if os.path.exists(CONFIG_FILENAME):
                shutil.copyfile(CONFIG_FILENAME, config_archive_path)
            else:
                with open(config_archive_path, 'w') as fptr:
                    fptr.write(
                        '(no {} file found in {})\n'.format(
                            CONFIG_FILENAME, os.getcwd()
                            )
                        )

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def archive_path(self, filename, suffix):
        '''Return the path to an archive file.'''
        archive_filename = '.'.join([filename, suffix])
        archive_path = os.path.join(ARTIFACT_ARCHIVE_DIR, archive_filename)
        return archive_path

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def call_aardvark_config(
            self,
            cmdline_option_spec=None,
            input_option_spec=None,
            prompt=True,
            short_flags=False
            ):
        '''Call aardvark config and interact as necessary.'''

        cmdline_option_spec = cmdline_option_spec or {}
        input_option_spec = input_option_spec or {}

        command = 'aardvark config' + ('' if prompt else ' --no-prompt')
        self.last_config_command = '{} {}'.format(
            command,
            get_config_option_string(
                cmdline_option_spec, short_flags=short_flags
                )
            )

        self.commands_issued.append(self.last_config_command)
        spawn_config = pexpect.spawn(self.last_config_command)

        self.conduct_config_prompt_sequence(
            spawn_config, input_option_spec
            )

        # If we didn't wrap up the session, something's amiss.
        self.assertFalse(spawn_config.isalive())

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def conduct_config_prompt_sequence(self, spawned, input_option_spec):
        '''Carry out the steps in the config prompt sequence.'''

        # The order is all that tells us which of these match in a pexpect
        # call, so we can't use a dict here.
        control_prompts = [
            (pexpect.EOF, 'eof'),
            (pexpect.TIMEOUT, 'timeout')
            ]
        config_option_prompts = [
            (v['config_prompt'], k)
            for k, v in CONFIG_OPTIONS.items()
            ]
        expect_prompts = [
            (r'(?i).*Do you use SWAG.*:', 'use_swag'),
            ]

        expect_prompts.extend(config_option_prompts)
        expect_prompts.extend(control_prompts)

        response_spec = input_option_spec
        response_spec['use_swag'] = (
            'y' if 'swag_bucket' in input_option_spec else 'N'
            )

        while spawned.isalive():

            prompt_index = spawned.expect(
                [x[0] for x in expect_prompts], timeout=EXPECT_TIMEOUT
                )
            self.last_transcript.append(spawned.after)

            prompt_received = expect_prompts[prompt_index][1]
            if prompt_received in [x[1] for x in control_prompts]:
                return

            response = response_spec.get(prompt_received)
            response = '' if response is None else response
            spawned.sendline(str(response))


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TestConfigNoPrompt(TestConfigBase):
    '''Test cases for config --no-prompt.'''

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(not PHANTOMJS_EXECUTABLE, INSTALL_PHANTOM)
    def test_no_prompt_defaults(self):
        '''Test with no-prompt and all default arguments.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_no_prompt_defaults'

        cmdline_option_spec = {}

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            prompt=False
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(cmdline_option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def test_no_prompt_all_parameters(self):
        '''Test with no-prompt and all parameters.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_no_prompt_all_parameters'

        cmdline_option_spec = {
            'swag_bucket': 'bucket_123',
            'aardvark_role': 'role_123',
            'phantom': 'phantom_123',
            'db_uri': 'db_uri_123',
            'num_threads': 4
            }

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            prompt=False
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(cmdline_option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def test_no_prompt_all_parameters_short(self):
        '''Test with no-prompt and short parameters.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_no_prompt_all_parameters_short'

        cmdline_option_spec = {
            'swag_bucket': 'bucket_123',
            'aardvark_role': 'role_123',
            'phantom': 'phantom_123',
            'db_uri': 'db_uri_123',
            'num_threads': 4
            }

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            short_flags=True,
            prompt=False
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(cmdline_option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def test_no_prompt_no_swag(self):
        '''Test with no-prompt and all non-swag parameters.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_no_prompt_no_swag'

        cmdline_option_spec = {
            'aardvark_role': 'role_123',
            'phantom': 'phantom_123',
            'db_uri': 'db_uri_123',
            'num_threads': 4
            }

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            prompt=False
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(cmdline_option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(PHANTOMJS_EXECUTABLE, HIDE_PHANTOM)
    def test_no_prompt_no_phantom_raises_error(self):
        '''Test with no-prompt and phantom neither found nor specified.

        This requires intervention to "hide" the phantom executable.
        '''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = (
            'test_no_prompt_no_phantom_raises_error'
            )

        cmdline_option_spec = {}

        # We really should check for an exception here but that happens
        # in the interactive session. We'll fudge it by just checking
        # that no config file is created.
        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            prompt=False
            )
        self.assertFalse(os.path.exists(CONFIG_FILENAME))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(PHANTOMJS_EXECUTABLE, HIDE_PHANTOM)
    def test_no_prompt_specify_phantom_no_executable(self):
        '''Test with no-prompt and phantom not found.

        This requires intervention to "hide" the phantom executable.
        '''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = (
            'test_no_prompt_specify_phantom_no_executable'
            )

        cmdline_option_spec = {
            'phantom': 'phantom_123',
            }

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            prompt=False
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(cmdline_option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TestConfigPrompt(TestConfigBase):
    '''Test cases for config with prompting.'''

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(not PHANTOMJS_EXECUTABLE, INSTALL_PHANTOM)
    def test_prompted_defaults(self):
        '''Test with no parameters specified.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_prompted_defaults'

        cmdline_option_spec = {}
        input_option_spec = {'num_threads': 4}

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            input_option_spec=input_option_spec
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(option_spec)
        expected_config = get_expected_config(option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    def test_prompted_all_cmdline_parameters(self):
        '''Test with all parameters passed as options.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_prompted_all_cmdline_parameters'

        cmdline_option_spec = {
            'swag_bucket': 'bucket_123',
            'aardvark_role': 'role_123',
            'phantom': 'phantom_123',
            'db_uri': 'db_uri_123',
            'num_threads': 4
            }
        input_option_spec = {}

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            input_option_spec=input_option_spec
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(option_spec)
        expected_config = get_expected_config(option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(not PHANTOMJS_EXECUTABLE, INSTALL_PHANTOM)
    def test_prompted_no_swag(self):
        '''Test with all non-swag parameters interactively.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_prompted_no_swag'

        cmdline_option_spec = {}
        input_option_spec = {
            'aardvark_role': 'role_123',
            'db_uri': 'db_uri_123',
            'num_threads': 4
            }

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            input_option_spec=input_option_spec
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(option_spec)
        expected_config = get_expected_config(option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(not PHANTOMJS_EXECUTABLE, INSTALL_PHANTOM)
    def test_prompted_nophantom_option(self):
        '''Test with all non-phantom parameters interactively.'''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = 'test_prompted_nophantom'

        cmdline_option_spec = {}
        input_option_spec = {
            'swag_bucket': 'bucket_123',
            'aardvark_role': 'role_123',
            'db_uri': 'db_uri_123',
            'num_threads': 4
            }

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=cmdline_option_spec,
            input_option_spec=input_option_spec
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(option_spec)
        expected_config = get_expected_config(option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(PHANTOMJS_EXECUTABLE, HIDE_PHANTOM)
    def test_prompted_no_phantom_raises_error(self):
        '''Test with phantom neither found nor specified.

        This requires intervention to "hide" the phantom executable.
        '''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = (
            'test_prompted_no_phantom_raises_error'
            )

        cmdline_option_spec = {}
        input_option_spec = {}

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        # We really should check for an exception here but that happens
        # in the interactive session. We'll fudge it by just checking
        # that no config file is created.
        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=option_spec,
            )
        self.assertFalse(os.path.exists(CONFIG_FILENAME))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(PHANTOMJS_EXECUTABLE, HIDE_PHANTOM)
    def test_prompted_input_phantom_no_executable(self):
        '''Test with phantom not found but entered interactively.

        This requires intervention to "hide" the phantom executable.
        '''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = (
            'test_prompted_input_phantom_no_executable'
            )

        cmdline_option_spec = {}
        input_option_spec = {
            'phantom': 'phantom_123',
            }

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=option_spec,
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    @unittest.skipIf(PHANTOMJS_EXECUTABLE, HIDE_PHANTOM)
    def test_prompted_cmdline_phantom_no_executable(self):
        '''Test with phantom not found but provided by parameter.

        This requires intervention to "hide" the phantom executable.
        '''

        # Turn on failed-case archive.
        self.archive_case_artifacts_as = (
            'test_prompted_input_phantom_no_executable'
            )

        cmdline_option_spec = {
            'phantom': 'phantom_123',
            }
        input_option_spec = {}

        # Combined, for validation.
        option_spec = dict(cmdline_option_spec, **input_option_spec)

        self.assertFalse(os.path.exists(CONFIG_FILENAME))
        self.call_aardvark_config(
            cmdline_option_spec=option_spec,
            )
        self.assertTrue(os.path.exists(CONFIG_FILENAME))

        found_config = load_configfile(cmdline_option_spec)
        expected_config = get_expected_config(option_spec)

        self.assertItemsEqual(expected_config.keys(), found_config.keys())
        for k, v in found_config.items():
            self.assertEqual((k, v), (k, expected_config[k]))

        # Turn off failed-case archive.
        self.archive_case_artifacts_as = None


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# Define test suite.
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
load_case = unittest.TestLoader().loadTestsFromTestCase
all_suites = {
    'testconfignoprompt': load_case(
        TestConfigNoPrompt
        ),
    'testconfigprompt': load_case(
        TestConfigPrompt
        )
    }

master_suite = unittest.TestSuite(all_suites.values())

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
if __name__ == '__main__':
    unittest.main()
