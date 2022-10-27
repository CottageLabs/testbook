# Testbook

A tool for converting Functional Test definitions in your codebase to HTML/CSV scripts for humans to work with

## Building a testbook

General form is

```
testbook [source dir] [out dir] -t [testbook base url] -a [application base url] -r [resources base url]
```

* **source dir** - the directory of testbook definition files.  This can be an arbitrary structure, and all yml files in that directory will be assumed to be testbook files
* **out dir** - the directory where the output files will be written.  If it does not exist it will be created
* **testbook base url** - the base url (excluding trailing slash) where the testbook will be made available online
* **application base url** - the base url (excluding the trailing slash) where the application being tested is located
* **resources base url** - the base url (excluding the trailing slash) where the resources are located

For example, to build a project on your local machine, using resources hosted on github:

```
testbook myproject/testbook myproject/testscripts -t http://localhost:8000 -a http://localhost:5000 -r https://raw.githubusercontent.com/MyOrg/myproject/develop/testscripts
```

This will read the tests defined in `myproject/testbook` and output HTML and CSV files to `myproject/testscripts`.

All internal testbook links will be prefixed with `http://localhost:8000`

All links into the application will be prefixed with `http://localhost:5000`

And all links to resource files will be prefixed with `https://raw.githubusercontent.com/MyOrg/myproject/develop/testscripts`


## Running the testbook

Testbook needs to run through a webserver, as it loads data asynchronously from the filesystem; you cannot view it at a `file:///` url.  It is designed for deployment to, e.g. github pages.  You can run it locally easily enough with any simple web server.  To do this in python, for example, go into the testbook output directory and run

```
python -m SimpleHTTPServer
```

This will bring your testbook up at `http://localhost:8000`.


## Testbook format

Testbook files are of the following format.

```yaml
suite: Name of the Test Suite
testset: Name for this set of tests

fragments:
  fragment_id:
    - step: Reusable step
    - step: Another reusable step

tests:
  - title: Title of this specific test
    context:
      any_key: any_value
    depends:
      - suite: Suite Name
        testset: Testset name
        test: Test name
    setup:
      - Setup instructions
    steps:
      - step: User Instructions for this step of the test
        path: /relative/path/to/relevant/page
      - step: Another step of the test
        resource: /relative/path/to/a/test/file.xml
      - step: A step of the test with a result
        results:
          - A result that the user can verify
      - include:
          fragment: fragment_id
```

When the files are read, the tests will be clustered by `suite` and then `testset`.  You can define the same `suite` and
`testset` in multiple files, and they will be aggregated together.

You may then define any number of re-usable fragments of test scripts.  This is done in a `fragments` field where each fragment is provided with a unique id.  The fragment may then contain an arbitrary number of `step`s.  Note that fragments can only be used within the file they are defined in (for now).

Each test consists of 
* a `title` which should be unique within this `testset`
* a `context` which allows you to include any key/value pairs for the user's information (they have no semantics within testbook)
* a `depends` list, which lists any number of tests which must be executed prior to this test in order for it to work.  This can contain a `suite`, `testset` and `test` as needed.
* a `setup` list, which should instruct the user how to prepare for the test
* a set of `steps`.  Each step may have the following:
    * a `step` (required) - the instructions for the user to execute the step
    * a `path` - a link to the application, to aid the user in getting to the right place to execute the test
    * a `resource` - a link to a test resource that the user may need (e.g. a file to upload to a web form)
    * a `results` list - any number of outcomes from the `step` that the user should check
    * an `include` directive - if this is present, none of the other entries defined above have any effect.  This defines a fragment to be included, and has a `fragment` field within it where you specify the fragment ID in the `fragments` section.

