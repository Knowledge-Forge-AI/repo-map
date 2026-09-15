module Example
  module Actions
    module Home
      class Index
        def handle(request, response)
          response.body = "home"
        end
      end
    end
  end
end
