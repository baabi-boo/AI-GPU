# SPDX-License-Identifier: Apache-2.0
include Makefile

MPM_TRANSPORT_TEST_OBJ := $(OBJ_DIR)/tests/mpm_transport_test.o
MPM_TRANSPORT_TEST := $(DESTDIR)/mpm_transport_test

.PHONY: test-mpm-transport clean-mpm-transport

test-mpm-transport: $(MPM_TRANSPORT_TEST)
	$(MPM_TRANSPORT_TEST)

$(MPM_TRANSPORT_TEST_OBJ): $(VORTEX_HOME)/tests/unittest/mpm_transport/main.cpp $(CONFIG_FILE)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(MPM_TRANSPORT_TEST): $(OBJS) $(MPM_TRANSPORT_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ $(LDFLAGS) -o $@

-include $(MPM_TRANSPORT_TEST_OBJ:.o=.d)

clean-exe: clean-mpm-transport
clean-mpm-transport:
	rm -f $(MPM_TRANSPORT_TEST)
