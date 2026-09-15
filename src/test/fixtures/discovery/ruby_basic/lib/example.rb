require_relative "example/service"
require "json"

module Example
  VERSION = "1.0"

  class Runner < BaseRunner
    include Helpers
    extend ClassMethods

    def call
      Service.new.call
    end

    def self.build
      new
    end
  end
end
