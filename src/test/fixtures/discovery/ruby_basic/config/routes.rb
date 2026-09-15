module Example
  class App < Hanami::App
    get "/home", to: "home.index"
  end
end
