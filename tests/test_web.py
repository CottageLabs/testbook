import unittest

from testbook.web import create_app


class CreateAppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_index_page_renders(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome to Testbook", response.data)


if __name__ == "__main__":
    unittest.main()

