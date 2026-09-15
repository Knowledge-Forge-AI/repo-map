module Example
  define_method("run_#{name}") { send(name) }
  class_eval("def generated; end")
end
