require "sinatra/base"

class App < Sinatra::Base
  get "/health" do
    erb :health
  end

  post "/items" do
    erb :item
  end
end
