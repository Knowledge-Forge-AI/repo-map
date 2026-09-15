import { createApp, defineComponent, ref } from "vue";

const App = defineComponent({
  setup() {
    const count = ref(0);
    return { count };
  },
});

createApp(App).mount("#app");
