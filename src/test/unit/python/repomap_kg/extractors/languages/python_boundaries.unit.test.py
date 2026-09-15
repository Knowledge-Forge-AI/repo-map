import unittest
from repomap_kg.extractors.languages.python import (
    PythonModuleIndex,
    extract_python_file_observations,
)
from repomap_kg.extractors.languages.python_imports import resolve_relative_base
from repomap_kg.extractors.languages.ruby import extract_ruby_file_observations

class PythonLanguageBoundariesUnitTests(unittest.TestCase):
    def test_python_import_helpers(self):
        self.assertEqual(resolve_relative_base("pkg.sub.module", "", 1), "pkg.sub")
        self.assertEqual(resolve_relative_base("pkg.sub.module", "", 2), "pkg")

    def test_python_web_frameworks_and_test_patterns(self):
        py_code = """
import pytest
from fastapi import FastAPI, Depends

app = FastAPI()

def get_db():
    yield None

@app.get("/items/{item_id}")
def read_item(item_id: int, db=Depends(get_db)):
    return {"item_id": item_id}

@pytest.fixture
def sample_data():
    return [1, 2, 3]

@pytest.mark.parametrize("val", [1, 2, 3])
def test_read_item(sample_data, val):
    assert val in sample_data
"""
        obs = extract_python_file_observations(
            "app/main.py",
            py_code,
            module_index=PythonModuleIndex.empty(),
        )
        self.assertEqual(obs[0].kind, "python.module")

    def test_ruby_extractor_boundaries(self):
        ruby_code = """
require 'json'
require_relative 'helpers/auth'

module Api
  class UsersController < ApplicationController
    def index
      render json: { users: [] }
    end
  end
end
"""
        obs = extract_ruby_file_observations("app/controllers/users_controller.rb", ruby_code)
        self.assertEqual(obs[0].kind, "ruby.file")

if __name__ == "__main__":
    unittest.main()
