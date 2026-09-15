import unittest

from repomap_kg.extractors.languages.ruby import extract_ruby_file_observations


class RubyExtractorUnitTests(unittest.TestCase):
    def test_rootpkg35_ruby_profile_helpers_are_reexported(self):
        import repomap_kg.extractors.languages.ruby as ruby
        import repomap_kg.extractors.languages.ruby_profiles as ruby_profiles
        helper_names = (
            "_definition_observation",
            "_gem_dependency_observations",
            "_gemfile_observations",
            "_gemspec_observations",
            "_observation",
            "_reference_observation",
            "_vagrant_config",
            "_vagrant_observations",
        )
        for name in helper_names:
            self.assertIs(getattr(ruby, name), getattr(ruby_profiles, name))

    def test_extracts_generic_modules_classes_methods_and_references(self):
        content = (
            'require_relative "example/service"\n'
            'require "json"\n'
            "module Example\n"
            '  VERSION = "1.0"\n'
            "  class Runner < BaseRunner\n"
            "    include Helpers\n"
            "    extend ClassMethods\n"
            "    def call\n"
            "    end\n"
            "    def self.build\n"
            "    end\n"
            "  end\n"
            "end\n"
        )

        observations = extract_ruby_file_observations(
            "lib/example.rb",
            content,
            repository_paths=frozenset({"lib/example.rb", "lib/example/service.rb"}),
        )
        by_kind = {observation.kind: observation for observation in observations}
        references = [item for item in observations if item.kind == "ruby.reference"]

        self.assertEqual(observations[0].kind, "ruby.file")
        self.assertEqual(observations[0].target, "ruby.file:file%3Alib%2Fexample.rb")
        self.assertEqual(observations[0].metadata["profile"], "generic_ruby")
        self.assertEqual(by_kind["ruby.module"].target, "ruby.module:Example")
        self.assertEqual(by_kind["ruby.class"].target, "ruby.class:Example%3A%3ARunner")
        self.assertEqual(by_kind["ruby.class"].metadata["superclass"], "BaseRunner")
        self.assertEqual(by_kind["ruby.method"].target, "ruby.method:Example%3A%3ARunner:call")
        self.assertEqual(
            by_kind["ruby.singleton_method"].target,
            "ruby.singleton_method:Example%3A%3ARunner:build",
        )
        self.assertEqual(
            by_kind["ruby.constant"].target,
            "ruby.constant:Example:VERSION",
        )
        self.assertIn(
            ("require_relative", "file:lib/example/service.rb"),
            {
                (reference.metadata["reference_kind"], reference.target)
                for reference in references
            },
        )
        self.assertIn(
            ("require", "external:ruby.require:json"),
            {
                (reference.metadata["reference_kind"], reference.target)
                for reference in references
            },
        )

    def test_detects_minitest_cases_and_methods(self):
        content = (
            'require "minitest/autorun"\n'
            "class ExampleTest < Minitest::Test\n"
            "  def test_call\n"
            "    assert_equal 1, 1\n"
            "  end\n"
            "end\n"
        )

        observations = extract_ruby_file_observations(
            "test/example_test.rb",
            content,
        )
        test_case = next(item for item in observations if item.kind == "ruby.test_case")
        test_method = next(item for item in observations if item.kind == "ruby.test_method")

        self.assertEqual(test_case.metadata["profile"], "minitest")
        self.assertEqual(test_case.metadata["test_framework"], "minitest")
        self.assertEqual(
            test_case.target,
            "ruby.test_case:file%3Atest%2Fexample_test.rb:ExampleTest",
        )
        self.assertEqual(test_method.metadata["method_name"], "test_call")
        self.assertEqual(
            test_method.target,
            (
                "ruby.test_method:"
                "ruby.test_case%3Afile%253Atest%252Fexample_test.rb%3AExampleTest:"
                "test_call"
            ),
        )

    def test_detects_minitest_spec_style_cases_without_text_identity(self):
        content = (
            'require "minitest/autorun"\n'
            'describe "Example service" do\n'
            '  it "does the safe thing" do\n'
            "  end\n"
            "end\n"
        )

        observations = extract_ruby_file_observations("test/service_spec.rb", content)
        test_case = next(item for item in observations if item.kind == "ruby.test_case")
        test_method = next(item for item in observations if item.kind == "ruby.test_method")

        self.assertEqual(test_case.metadata["test_name_summary"], "Example service")
        self.assertEqual(test_case.metadata["identity_strength"], "structural")
        self.assertEqual(test_case.target, "ruby.test_case:file%3Atest%2Fservice_spec.rb:describe%5B1%5D")
        assert test_case.target is not None
        self.assertEqual(test_method.metadata["test_name_summary"], "does the safe thing")
        self.assertEqual(test_method.metadata["method_name"], "it[1]")
        self.assertNotIn("Example service", test_case.target)

    def test_detects_vagrantfile_static_config_without_command_bodies(self):
        content = (
            'Vagrant.configure("2") do |config|\n'
            '  config.vm.box = "example/ubuntu"\n'
            '  config.vm.provider "vmware_desktop"\n'
            '  config.vm.network "private_network", type: "dhcp"\n'
            '  config.vm.synced_folder "./src", "/vagrant/src"\n'
            '  config.vm.provision "shell", inline: "echo fake-secret-token"\n'
            "end\n"
        )

        observations = extract_ruby_file_observations(
            "Vagrantfile",
            content,
            repository_paths=frozenset({"Vagrantfile", "src"}),
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        vagrant_configs = [
            item for item in observations if item.kind == "ruby.vagrant_config"
        ]
        references = [item for item in observations if item.kind == "ruby.reference"]

        self.assertNotIn("fake-secret-token", payload)
        self.assertIn(
            ("box", "external:vagrant-box:example%2Fubuntu"),
            {
                (item.metadata["vagrant_key"], item.target)
                for item in references
                if item.metadata.get("vagrant_key")
            },
        )
        self.assertIn(
            ("synced_folder", "file:src"),
            {
                (item.metadata["vagrant_key"], item.target)
                for item in references
                if item.metadata.get("vagrant_key")
            },
        )
        provisioner = next(
            item for item in vagrant_configs
            if item.metadata.get("vagrant_key") == "provision"
        )
        network = next(
            item for item in vagrant_configs
            if item.metadata.get("vagrant_key") == "network"
        )
        self.assertEqual(network.metadata["value_summary"], "private_network")
        self.assertTrue(provisioner.metadata["redacted"])
        self.assertTrue(provisioner.metadata["dynamic"])

    def test_vagrant_synced_folder_repo_root_does_not_crash(self):
        content = (
            'Vagrant.configure("2") do |config|\n'
            '  config.vm.synced_folder ".", "/vagrant"\n'
            "end\n"
        )

        observations = extract_ruby_file_observations(
            "Vagrantfile",
            content,
            repository_paths=frozenset({"Vagrantfile"}),
        )
        reference = next(
            item for item in observations if item.kind == "ruby.reference"
        )

        self.assertEqual(reference.metadata["vagrant_key"], "synced_folder")
        self.assertEqual(reference.target, "unknown:file:repository-root-ruby-reference")
        self.assertEqual(reference.metadata["resolution_reason"], "path")

    def test_detects_sinatra_routes_and_template_references(self):
        content = (
            'require "sinatra/base"\n'
            "class App < Sinatra::Base\n"
            "  configure do\n"
            "  end\n"
            '  get "/health" do\n'
            "    erb :health\n"
            "  end\n"
            "  before do\n"
            "  end\n"
            "end\n"
        )

        observations = extract_ruby_file_observations(
            "sinatra_app.rb",
            content,
            repository_paths=frozenset({"sinatra_app.rb", "views/health.erb"}),
        )
        route = next(item for item in observations if item.kind == "ruby.route")
        references = [item for item in observations if item.kind == "ruby.reference"]

        self.assertEqual(route.metadata["profile"], "sinatra")
        self.assertEqual(route.metadata["route_method"], "get")
        self.assertEqual(route.metadata["route_pattern"], "/health")
        self.assertEqual(route.target, "ruby.route:file%3Asinatra_app.rb:%2Froutes%2Fget%3A%2Fhealth")
        self.assertIn(
            "file:views/health.erb",
            {reference.target for reference in references},
        )
        self.assertIn(
            ("configure", "sinatra"),
            {
                (item.metadata.get("dsl_name"), item.metadata.get("profile"))
                for item in observations
                if item.kind == "ruby.dsl"
            },
        )

    def test_detects_hanami_routes_rake_tasks_and_gem_dependencies(self):
        routes = extract_ruby_file_observations(
            "config/routes.rb",
            'module Example\n  class App < Hanami::App\n    get "/home", to: "home.index"\n  end\nend\n',
        )
        rake = extract_ruby_file_observations(
            "Rakefile",
            (
                'desc "Run tests"\n'
                "task :test do\n"
                "end\n"
                "namespace :fixtures do\n"
                "end\n"
            ),
        )
        gemfile = extract_ruby_file_observations(
            "Gemfile",
            'source "https://user:fake-token@example.invalid/rubygems"\ngem "rack", "~> 3.0"\n',
        )
        gemspec = extract_ruby_file_observations(
            "example.gemspec",
            'spec.add_development_dependency "minitest", "~> 5.0"\n',
        )
        payload = "\n".join(
            item.to_json_line()
            for collection in (routes, rake, gemfile, gemspec)
            for item in collection
        )

        self.assertIn("hanami", {item.metadata.get("profile") for item in routes})
        self.assertIn("ruby.route", {item.kind for item in routes})
        self.assertIn("ruby.dsl", {item.kind for item in rake})
        self.assertIn(
            ("namespace", "fixtures"),
            {
                (item.metadata.get("dsl_name"), item.metadata.get("namespace_name"))
                for item in rake
                if item.kind == "ruby.dsl"
            },
        )
        self.assertIn("ruby.gem_dependency", {item.kind for item in gemfile})
        self.assertIn("ruby.gem_dependency", {item.kind for item in gemspec})
        self.assertIn(
            "external:ruby-gem:rack",
            {item.target for item in gemfile if item.kind == "ruby.reference"},
        )
        self.assertIn(
            "external:ruby-gem:minitest",
            {item.target for item in gemspec if item.kind == "ruby.reference"},
        )
        self.assertNotIn("fake-token", payload)

    def test_dynamic_constructs_emit_safe_diagnostics_and_redact_secret_literals(self):
        content = (
            'API_KEY = "fake-ruby-secret"\n'
            'define_method("run_#{name}") { send(name) }\n'
            'class_eval("def unsafe; end")\n'
            'ENV.fetch("SECRET_TOKEN")\n'
        )

        observations = extract_ruby_file_observations("lib/dynamic.rb", content)
        payload = "\n".join(item.to_json_line() for item in observations)
        dynamic_observations = [
            item
            for item in observations
            if item.metadata.get("dynamic") or item.metadata.get("redacted")
        ]

        self.assertNotIn("fake-ruby-secret", payload)
        self.assertGreaterEqual(len(dynamic_observations), 3)
        self.assertIn(
            "ruby.parse_error",
            {item.kind for item in observations},
        )
        redacted_constant = next(
            item for item in observations
            if item.kind == "ruby.constant" and item.name == "API_KEY"
        )
        self.assertTrue(redacted_constant.metadata["redacted"])


if __name__ == "__main__":
    unittest.main()
