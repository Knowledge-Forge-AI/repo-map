require_relative "test_helper"

class ExampleTest < Minitest::Test
  def test_call
    assert_equal :ok, Example::Service.new.call
  end
end
